import streamlit as st
import time
import json
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
st.set_page_config(page_title="JAWS Accessibility Agent", layout="wide", page_icon="🧑‍🦯")

# --- JAWS SIMULATOR CLASS ---
class JawsAgent:
    def __init__(self, headless=True):
        options = webdriver.ChromeOptions()
        
        # W Streamlit Cloud przeglądarka ZAWSZE musi być w trybie headless
        if headless:
            options.add_argument("--headless") 
            
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Flagi krytyczne dla środowisk serwerowych / Docker / Streamlit Cloud
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        
        try:
            # PRÓBA 1: Środowisko Streamlit Cloud (Linux)
            # Szukamy ścieżek z zainstalowanych paczek w packages.txt
            options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
            self.driver = webdriver.Chrome(service=service, options=options)
            
        except Exception as e:
            # PRÓBA 2: Fallback dla środowiska lokalnego (Windows/Mac)
            print(f"Błąd uruchamiania Chromium ze ścieżki systemowej: {e}")
            print("Uruchamiam fallback: webdriver-manager (lokalnie)...")
            options.binary_location = "" # Czyszczenie ścieżki
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)

        self.actions = ActionChains(self.driver)
        self.logs = []
        self.violations = []
        
        # Inicjalizacja JS dla obliczania nazwy dostępnościowej
        self.js_acc_info = """
        function getAccInfo(el) {
            if (!el || el === document.body) return {name: 'Body', role: 'document'};
            let name = el.getAttribute('aria-label') || el.getAttribute('alt');
            if (!name && el.getAttribute('aria-labelledby')) {
                let labelEl = document.getElementById(el.getAttribute('aria-labelledby'));
                if (labelEl) name = labelEl.innerText;
            }
            if (!name) name = el.innerText || el.value || el.placeholder || '';
            let role = el.getAttribute('role') || el.tagName.toLowerCase();
            if (role === 'a') role = 'link';
            if (role === 'input' && el.type !== 'button' && el.type !== 'submit') role = 'edit';
            if (el.tagName.toLowerCase() === 'button' || (role === 'input' && (el.type === 'button' || el.type === 'submit'))) role = 'button';
            if (role.match(/^h[1-6]$/)) role = 'heading level ' + role.substring(1);
            return {
                name: name.trim().replace(/\\n/g, ' '),
                role: role
            };
        }
        return getAccInfo(arguments[0]);
        """

    def log_jaws(self, action, element_text, role, state=""):
        state_str = f" [{state}]" if state else ""
        log_entry = f"JAWS: '{role}: {element_text}'{state_str} [{action}]"
        self.logs.append({"action": action, "role": role, "text": element_text, "state": state, "time": time.strftime("%H:%M:%S")})
        return log_entry

    def press_key(self, key_name, key_code):
        self.actions.send_keys(key_code).perform()
        time.sleep(0.5) # Czekamy na reakcję UI
        active_element = self.driver.switch_to.active_element
        
        # Wyciągamy dane dostępnościowe
        info = self.driver.execute_script(self.js_acc_info, active_element)
        
        # WCAG 2.4.7 Focus Visibility Check
        has_focus = self.driver.execute_script(
            "return window.getComputedStyle(arguments[0]).outlineWidth !== '0px' || window.getComputedStyle(arguments[0]).boxShadow !== 'none';", 
            active_element
        )
        if not has_focus and info['name']:
            self.violations.append({
                "type": "Focus Visibility (2.4.7)", 
                "element": info['name'], 
                "issue": "Brak wyraźnego wskaźnika focusu (outline/box-shadow)."
            })

        return self.log_jaws(key_name, info['name'], info['role'])

    def check_aria_live(self):
        script = """
        let liveRegions = document.querySelectorAll('[aria-live="polite"], [aria-live="assertive"], [role="status"], [role="alert"]');
        let announcements = [];
        liveRegions.forEach(region => {
            if (region.innerText.trim() !== '' && region.dataset.lastSpoken !== region.innerText) {
                announcements.push(region.innerText.trim());
                region.dataset.lastSpoken = region.innerText;
            }
        });
        return announcements;
        """
        announcements = self.driver.execute_script(script)
        for ann in announcements:
            self.log_jaws("ARIA-live", ann, "alert/status")

    def run_scenario(self, url):
        yield "Rozpoczynam ładowanie strony..."
        self.driver.get(url)
        time.sleep(3) # Czekamy na załadowanie (w produkcji użyć WebDriverWait)
        self.log_jaws("Page Load", self.driver.title, "Title")
        yield "Strona załadowana. Rozpoczynam nawigację klawiaturą (Tab/Enter)..."

        # Symulacja nawigacji TAB
        for _ in range(5):
            yield self.press_key("Tab", Keys.TAB)
            self.check_aria_live()

        yield "Symulacja skrótu 'H' (Nagłówki)..."
        # Uproszczony skok do pierwszego H1
        h1 = self.driver.execute_script("return document.querySelector('h1, h2, h3');")
        if h1:
            info = self.driver.execute_script(self.js_acc_info, h1)
            yield self.log_jaws("H", info['name'], info['role'])

        yield "Zapisuję stan (Screenshot)..."
        screenshot_path = "current_state.png"
        self.driver.save_screenshot(screenshot_path)
        
        self.driver.quit()
        yield {"status": "done", "screenshot": screenshot_path, "logs": self.logs, "violations": self.violations}

# --- STREAMLIT UI ---
st.title("🧑‍🦯 JAWS Accessibility E2E Agent")
st.markdown("Automatyczny tester WCAG 2.2 symulujący nawigację za pomocą czytnika ekranu (Tylko klawiatura).")

with st.sidebar:
    st.header("Konfiguracja Testu")
    target_url = st.text_input("URL do testów:", value="https://www.lyreco.com/webshop/NLBE/wslogin")
    
    # Przełącznik Headless (Zawsze prawda dla bezpieczeństwa w chmurze, ale opcja jest)
    run_headless = st.checkbox("Uruchom w tle (Headless)", value=True, help="W Streamlit Cloud zawsze używany jest tryb Headless.")
    
    start_test = st.button("🚀 Uruchom Audyt JAWS", type="primary", use_container_width=True)

if start_test:
    st.subheader(f"Audyt w toku: {target_url}")
    
    log_container = st.empty()
    progress_bar = st.progress(0)
    
    # Inicjalizacja Agenta (Pamiętaj o wymuszeniu Headless w chmurze)
    agent = JawsAgent(headless=run_headless)
    scenario_generator = agent.run_scenario(target_url)
    
    output_console = ""
    result_data = None
    
    # Czytanie z generatora na żywo
    step_count = 0
    for step in scenario_generator:
        step_count += 1
        progress_bar.progress(min(step_count * 15, 100))
        
        if isinstance(step, str):
            output_console += f"> {step}\n"
            log_container.code(output_console, language="log")
        elif isinstance(step, dict) and step.get("status") == "done":
            result_data = step
            progress_bar.progress(100)

    if result_data:
        st.success("Audyt zakończony!")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("### 📝 Logi JAWS (Co słyszy użytkownik)")
            st.dataframe(result_data["logs"], use_container_width=True)
            
            # Przycisk pobierania JSON
            report_json = json.dumps({
                "url": target_url,
                "logs": result_data["logs"],
                "violations": result_data["violations"]
            }, indent=4, ensure_ascii=False)
            
            st.download_button(
                label="📥 Pobierz pełny Raport (JSON)",
                data=report_json,
                file_name="jaws_audit_report.json",
                mime="application/json",
            )

        with col2:
            st.markdown("### 📸 Ostatni ekran")
            if os.path.exists(result_data["screenshot"]):
                st.image(result_data["screenshot"])
            
            st.markdown("### 🚨 Naruszenia WCAG (Klawiatura/Focus)")
            if result_data["violations"]:
                for v in result_data["violations"]:
                    st.error(f"**{v['type']}**: {v['element']} - {v['issue']}")
            else:
                st.success("Nie wykryto oczywistych naruszeń w zbadanej ścieżce.")
