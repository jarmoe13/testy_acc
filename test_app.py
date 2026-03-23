import streamlit as st
import time
import json
import os
import io
from gtts import gTTS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
st.set_page_config(page_title="JAWS Accessibility Agent", layout="wide", page_icon="🧑‍🦯")

# --- AUDIO GENERATOR ---
def generate_audio_log(logs):
    """Przetwarza logi JAWS na plik audio."""
    if not logs:
        return None
        
    spoken_text = "Rozpoczynam audyt. "
    for entry in logs:
        action = entry['action']
        role = entry['role']
        text = entry['text']
        
        if role == "Title":
            spoken_text += f"Załadowano stronę. Tytuł: {text}. "
        elif action == "Tab":
            if "Pusty focus" not in text:
                spoken_text += f"{role}, {text}. "
        elif action == "H":
            spoken_text += f"Nagłówek, {role}, {text}. "
        elif action == "ARIA-live":
            spoken_text += f"Komunikat ekranowy: {text}. "

    try:
        # Generowanie audio (lang='pl' dla polskiego lektora)
        tts = gTTS(text=spoken_text, lang='pl', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        print(f"Błąd generowania audio: {e}")
        return None

# --- JAWS SIMULATOR CLASS ---
class JawsAgent:
    def __init__(self, headless=True):
        options = webdriver.ChromeOptions()
        
        if headless:
            options.add_argument("--headless") 
            
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        
        try:
            options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            options.binary_location = "" 
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)

        self.actions = ActionChains(self.driver)
        self.logs = []
        self.violations = []
        
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

    def apply_cookie_bypass(self):
        script = """
        const bannerSelectors = [
            '#usercentrics-root',           
            '[data-testid="uc-app-container"]', 
            '#onetrust-consent-sdk',        
            '#CybotCookiebotDialog',        
            '#cookie-notice',               
            '#cookie-law-info-bar',         
            '.cookie-banner',               
            '.cc-window',                   
            '[id*="cookie-banner"]',        
            '[id*="cookie-consent"]',
            '[class*="cookie-banner"]',     
            '[class*="cookie-consent"]'
        ];

        let wasRemoved = false;
        bannerSelectors.forEach(selector => {
            let elements = document.querySelectorAll(selector);
            elements.forEach(el => {
                el.remove();
                wasRemoved = true;
            });
        });
        
        let backdrops = document.querySelectorAll('.modal-backdrop, .onetrust-pc-dark-filter, [class*="overlay"], [class*="backdrop"]');
        backdrops.forEach(bg => bg.remove());

        document.body.style.overflow = 'auto';
        document.body.style.position = 'static';
        
        return wasRemoved;
        """
        messages = []
        try:
            messages.append("Uruchamiam uniwersalny skrypt czyszczący banery zgód...")
            time.sleep(3) 
            removed = self.driver.execute_script(script)
            if removed:
                messages.append("✅ Znaleziono i usunięto baner(y) z drzewa DOM! Odblokowano scrollowanie.")
            else:
                messages.append("⚠️ Nie znaleziono żadnego znanego banera. (Strona może go nie mieć).")
            time.sleep(1) 
        except Exception as e:
            messages.append(f"❌ Błąd podczas usuwania banera: {e}")
        return messages

    def log_jaws(self, action, element_text, role, state=""):
        state_str = f" [{state}]" if state else ""
        log_entry = f"JAWS: '{role}: {element_text}'{state_str} [{action}]"
        self.logs.append({"action": action, "role": role, "text": element_text, "state": state, "time": time.strftime("%H:%M:%S")})
        return log_entry

    def press_key(self, key_name, key_code):
        try:
            self.actions.send_keys(key_code).perform()
        except Exception:
            try:
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(key_code)
            except:
                pass
                
        time.sleep(0.5)
        
        try:
            active_element = self.driver.switch_to.active_element
            active_element.tag_name
        except Exception:
            try:
                active_element = self.driver.execute_script("return document.activeElement || document.body;")
            except:
                active_element = None

        if not active_element:
            return self.log_jaws(key_name, "[Pusty focus lub utracono element]", "unknown")

        try:
            info = self.driver.execute_script(self.js_acc_info, active_element)
            
            has_focus = self.driver.execute_script(
                "return window.getComputedStyle(arguments[0]).outlineWidth !== '0px' || window.getComputedStyle(arguments[0]).boxShadow !== 'none';", 
                active_element
            )
            if not has_focus and info['name'] and info['name'] != 'Body':
                self.violations.append({
                    "type": "Focus Visibility (2.4.7)", 
                    "element": info['name'], 
                    "issue": "Brak wyraźnego wskaźnika focusu (outline/box-shadow)."
                })
        except Exception:
            return self.log_jaws(key_name, "[Błąd analizy elementu]", "error")

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
        try:
            announcements = self.driver.execute_script(script)
            for ann in announcements:
                self.log_jaws("ARIA-live", ann, "alert/status")
        except:
            pass

    def run_scenario(self, url, bypass_banner=True):
        yield f"Rozpoczynam audyt dla URL: {url}"

        yield f"Nawiguję do: {url}"
        self.driver.get(url) 
        time.sleep(3) 
        
        if bypass_banner:
            yield "Opcja omijania włączona. Próbuję usunąć baner zgód z DOM..."
            bypass_messages = self.apply_cookie_bypass()
            for msg in bypass_messages:
                yield msg
            
            # --- SPORTANO FIX: Twardy reset focusu na <body> po usunięciu modala ---
            try:
                self.driver.execute_script("""
                    let b = document.querySelector('body');
                    if(b) {
                        b.tabIndex = -1;
                        b.focus();
                    }
                """)
                yield "Wykonano twardy reset focusu (zabezpieczenie przed błędem nawigacji)."
            except:
                pass
        else:
            yield "Testowanie wariantu Z BANEREM (omijanie wyłączone)."

        self.log_jaws("Page Load", self.driver.title, "Title")
        yield f"Strona gotowa. Rozpoczynam nawigację klawiaturą (Tab)..."

        for _ in range(5):
            yield self.press_key("Tab", Keys.TAB)
            self.check_aria_live()

        yield "Symulacja skrótu 'H' (Skok do nagłówków)..."
        try:
            h_element = self.driver.execute_script("return document.querySelector('h1, h2, h3');")
            if h_element:
                info = self.driver.execute_script(self.js_acc_info, h_element)
                yield self.log_jaws("H", info['name'], info['role'])
            else:
                yield "JAWS: 'Brak nagłówków' [H]"
        except:
            pass

        yield "Zapisuję stan końcowy audytu (Screenshot)..."
        screenshot_path = "current_state.png"
        try:
            self.driver.save_screenshot(screenshot_path)
        except:
            pass
        
        self.driver.quit()
        yield {"status": "done", "screenshot": screenshot_path, "logs": self.logs, "violations": self.violations}

# --- STREAMLIT UI ---
st.title("🧑‍🦯 JAWS Accessibility E2E Agent")
st.markdown("Automatyczny tester WCAG 2.2 symulujący nawigację za pomocą czytnika ekranu (Tylko klawiatura).")

with st.sidebar:
    st.header("Konfiguracja Testu")
    target_url = st.text_input("URL do testów:", value="https://www.lyreco.com/webshop/NLBE/wslogin")
    
    bypass_banner_ui = st.checkbox(
        "Pomiń banner RODO/Cookies", 
        value=True, 
        help="Zaznacz, aby agent automatycznie usunął banery systemów CMP z drzewa DOM."
    )
    
    run_headless = st.checkbox("Uruchom w tle (Headless)", value=True, help="W Streamlit Cloud zawsze używany jest tryb Headless.")
    
    start_test = st.button("🚀 Uruchom Audyt JAWS", type="primary", use_container_width=True)

if start_test:
    st.subheader(f"Audyt w toku: {target_url}")
    if bypass_banner_ui:
        st.info("Test wariantu: **BEZ** bannera (Automatyczne usuwanie aktywne)")
    else:
        st.warning("Test wariantu: **Z** bannerem na start")
    
    log_container = st.empty()
    progress_bar = st.progress(0)
    
    is_cloud = os.path.exists("/mount/src")
    headless_mode = True if is_cloud else run_headless
    
    agent = JawsAgent(headless=headless_mode)
    scenario_generator = agent.run_scenario(target_url, bypass_banner=bypass_banner_ui)
    
    output_console = ""
    result_data = None
    
    step_count = 0
    total_steps = 10 
    for step in scenario_generator:
        step_count += 1
        progress_bar.progress(min(int(step_count * (100 / total_steps)), 100))
        
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
            import pandas as pd
            df_logs = pd.DataFrame(result_data["logs"])
            if not df_logs.empty:
                st.dataframe(df_logs[['time', 'action', 'role', 'text', 'state']], use_container_width=True)
            else:
                st.info("Brak logów.")
            
            # --- DODANY ODTWARZACZ AUDIO ---
            st.markdown("### 🎧 Posłuchaj doświadczenia użytkownika (Audio)")
            with st.spinner("Generowanie pliku audio..."):
                audio_file = generate_audio_log(result_data["logs"])
                if audio_file:
                    st.audio(audio_file, format='audio/mp3')
                else:
                    st.warning("Nie udało się wygenerować audio.")
            
            report_json = json.dumps({
                "url": target_url,
                "timestamp": time.time(),
                "bypass_banner": bypass_banner_ui,
                "logs": result_data["logs"],
                "violations": result_data["violations"]
            }, indent=4, ensure_ascii=False)
            
            st.download_button(
                label="📥 Pobierz pełny Raport (JSON)",
                data=report_json,
                file_name=f"jaws_audit_report_{'nobanner' if bypass_banner_ui else 'withbanner'}.json",
                mime="application/json",
            )

        with col2:
            st.markdown("### 📸 Stan końcowy strony")
            if os.path.exists(result_data["screenshot"]):
                st.image(result_data["screenshot"], caption=f"Zrzut ekranu po sekwencji (Bypass: {bypass_banner_ui}).")
            
            st.markdown("### 🚨 Automatycznie wykryte naruszenia WCAG (Klawiatura/Focus)")
            if result_data["violations"]:
                for v in result_data["violations"]:
                    st.error(f"**{v['type']}**: {v['element']} - {v['issue']}")
            else:
                st.success("W zbadanej ścieżce nie wykryto oczywistych naruszeń WCAG (dot. wskaźnika focusu).")
