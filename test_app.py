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
    """Processes JAWS logs into an audio file."""
    if not logs:
        return None
        
    spoken_text = "Starting audit. "
    for entry in logs:
        action = entry['action']
        role = entry['role']
        text = entry['text']
        
        if role == "Title":
            spoken_text += f"Page loaded. Title: {text}. "
        elif action == "Tab":
            if "Empty focus" not in text:
                spoken_text += f"{role}, {text}. "
        elif action == "H":
            spoken_text += f"Heading, {role}, {text}. "
        elif action == "ARIA-live":
            spoken_text += f"Screen announcement: {text}. "

    try:
        # Generating audio (lang='en' for English voice)
        tts = gTTS(text=spoken_text, lang='en', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        print(f"Audio generation error: {e}")
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
            messages.append("Running universal consent banner cleanup script...")
            time.sleep(3) 
            removed = self.driver.execute_script(script)
            if removed:
                messages.append("✅ Found and removed banner(s) from DOM! Scrolling unlocked.")
            else:
                messages.append("⚠️ No known banner found. (The page might not have one).")
            time.sleep(1) 
        except Exception as e:
            messages.append(f"❌ Error during banner removal: {e}")
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
            return self.log_jaws(key_name, "[Empty focus or element lost]", "unknown")

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
                    "issue": "Missing clear focus indicator (outline/box-shadow)."
                })
        except Exception:
            return self.log_jaws(key_name, "[Element analysis error]", "error")

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
        yield f"Starting audit for URL: {url}"

        yield f"Navigating to: {url}"
        self.driver.get(url) 
        time.sleep(3) 
        
        if bypass_banner:
            yield "Bypass option enabled. Attempting to remove consent banner from DOM..."
            bypass_messages = self.apply_cookie_bypass()
            for msg in bypass_messages:
                yield msg
            
            # --- SPORTANO FIX: Hard focus reset to <body> after modal removal ---
            try:
                self.driver.execute_script("""
                    let b = document.querySelector('body');
                    if(b) {
                        b.tabIndex = -1;
                        b.focus();
                    }
                """)
                yield "Performed hard focus reset (navigation error safeguard)."
            except:
                pass
        else:
            yield "Testing WITH BANNER variant (bypass disabled)."

        self.log_jaws("Page Load", self.driver.title, "Title")
        yield f"Page ready. Starting keyboard navigation (Tab)..."

        for _ in range(5):
            yield self.press_key("Tab", Keys.TAB)
            self.check_aria_live()

        yield "Simulating 'H' shortcut (Jump to headings)..."
        try:
            h_element = self.driver.execute_script("return document.querySelector('h1, h2, h3');")
            if h_element:
                info = self.driver.execute_script(self.js_acc_info, h_element)
                yield self.log_jaws("H", info['name'], info['role'])
            else:
                yield "JAWS: 'No headings found' [H]"
        except:
            pass

        yield "Saving final audit state (Screenshot)..."
        screenshot_path = "current_state.png"
        try:
            self.driver.save_screenshot(screenshot_path)
        except:
            pass
        
        self.driver.quit()
        yield {"status": "done", "screenshot": screenshot_path, "logs": self.logs, "violations": self.violations}

# --- STREAMLIT UI ---
st.title("🧑‍🦯 JAWS Accessibility E2E Agent")
st.markdown("Automated WCAG 2.2 tester simulating screen reader navigation (Keyboard only).")

with st.sidebar:
    st.header("Test Configuration")
    target_url = st.text_input("Target URL:", value="https://www.lyreco.com/webshop/NLBE/wslogin")
    
    bypass_banner_ui = st.checkbox(
        "Bypass GDPR/Cookie Banner", 
        value=True, 
        help="Check to let the agent automatically remove CMP banners from the DOM."
    )
    
    run_headless = st.checkbox("Run in background (Headless)", value=True, help="Streamlit Cloud always uses Headless mode.")
    
    start_test = st.button("🚀 Run JAWS Audit", type="primary", use_container_width=True)

if start_test:
    st.subheader(f"Audit in progress: {target_url}")
    if bypass_banner_ui:
        st.info("Testing variant: **WITHOUT** banner (Auto-removal active)")
    else:
        st.warning("Testing variant: **WITH** banner on start")
    
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
        st.success("Audit completed!")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("### 📝 JAWS Logs (What the user hears)")
            import pandas as pd
            df_logs = pd.DataFrame(result_data["logs"])
            if not df_logs.empty:
                st.dataframe(df_logs[['time', 'action', 'role', 'text', 'state']], use_container_width=True)
            else:
                st.info("No logs.")
            
            # --- DODANY ODTWARZACZ AUDIO ---
            st.markdown("### 🎧 Listen to the user experience (Audio)")
            with st.spinner("Generating audio file..."):
                audio_file = generate_audio_log(result_data["logs"])
                if audio_file:
                    st.audio(audio_file, format='audio/mp3')
                else:
                    st.warning("Failed to generate audio.")
            
            report_json = json.dumps({
                "url": target_url,
                "timestamp": time.time(),
                "bypass_banner": bypass_banner_ui,
                "logs": result_data["logs"],
                "violations": result_data["violations"]
            }, indent=4, ensure_ascii=False)
            
            st.download_button(
                label="📥 Download Full Report (JSON)",
                data=report_json,
                file_name=f"jaws_audit_report_{'nobanner' if bypass_banner_ui else 'withbanner'}.json",
                mime="application/json",
            )

        with col2:
            st.markdown("### 📸 Final page state")
            if os.path.exists(result_data["screenshot"]):
                st.image(result_data["screenshot"], caption=f"Screenshot after sequence (Bypass: {bypass_banner_ui}).")
            
            st.markdown("### 🚨 Automatically detected WCAG violations (Keyboard/Focus)")
            if result_data["violations"]:
                for v in result_data["violations"]:
                    st.error(f"**{v['type']}**: {v['element']} - {v['issue']}")
            else:
                st.success("No obvious WCAG violations detected in the tested path (regarding focus indicator).")
