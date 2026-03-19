def apply_cookie_bypass(self):
        """Używa JavaScriptu, aby znaleźć i kliknąć przycisk akceptacji cookies. Działa o wiele stabilniej niż wstrzykiwanie ciasteczek."""
        script = """
        // Szukamy po popularnych ID systemów consent (np. OneTrust)
        let targetBtn = document.querySelector('#onetrust-accept-btn-handler') || 
                        document.querySelector('[data-testid="uc-accept-all-button"]');
        
        // Jeśli nie znaleziono po ID, szukamy po tekście przycisku
        if (!targetBtn) {
            const acceptTexts = ['Akceptuj wszystkie', 'Accept all', 'Akceptuj', 'Zgadzam się', 'Accept'];
            let buttons = Array.from(document.querySelectorAll('button, a.btn'));
            targetBtn = buttons.find(b => acceptTexts.some(t => b.innerText.trim().includes(t)));
        }
        
        if (targetBtn) {
            targetBtn.click();
            return true;
        }
        return false;
        """
        
        messages = []
        try:
            messages.append("Szukam banera cookies, aby go zamknąć...")
            
            # Banery ładują się asynchronicznie, więc próbujemy przez 5 sekund
            clicked = False
            for _ in range(5):
                clicked = self.driver.execute_script(script)
                if clicked:
                    messages.append("✅ Znaleziono i kliknięto 'Akceptuj wszystkie'!")
                    time.sleep(1.5) # Dajemy czas na animację zniknięcia banera z drzewa DOM
                    break
                time.sleep(1)
                
            if not clicked:
                messages.append("⚠️ Nie znaleziono przycisku akceptacji (baner mógł się nie załadować).")
                
        except Exception as e:
            messages.append(f"❌ Błąd podczas zamykania banera: {e}")
            
        return messages

    def run_scenario(self, url, bypass_banner=True):
        yield f"Rozpoczynam audyt dla URL: {url}"

        # 1. Najpierw ładujemy docelową stronę
        yield f"Nawiguję do: {url}"
        self.driver.get(url) 
        time.sleep(3) # Czekamy na wyrenderowanie Reacta/Angulara
        
        # 2. DOPIERO TERAZ zamykamy baner (jeśli opcja jest włączona)
        if bypass_banner:
            yield "Opcja omijania włączona. Próbuję usunąć baner zgód..."
            bypass_messages = self.apply_cookie_bypass()
            for msg in bypass_messages:
                yield msg
        else:
            yield "Testowanie wariantu Z BANEREM (omijanie wyłączone)."

        self.log_jaws("Page Load", self.driver.title, "Title")
        yield f"Strona gotowa. Rozpoczynam nawigację klawiaturą (Tab)..."

        # 3. Symulacja nawigacji TAB
        for _ in range(5):
            yield self.press_key("Tab", Keys.TAB)
            self.check_aria_live()

        yield "Symulacja skrótu 'H' (Skok do nagłówków)..."
        h_element = self.driver.execute_script("return document.querySelector('h1, h2, h3');")
        if h_element:
            info = self.driver.execute_script(self.js_acc_info, h_element)
            yield self.log_jaws("H", info['name'], info['role'])
        else:
            yield "JAWS: 'Brak nagłówków' [H]"

        yield "Zapisuję stan końcowy audytu (Screenshot)..."
        screenshot_path = "current_state.png"
        self.driver.save_screenshot(screenshot_path)
        
        self.driver.quit()
        yield {"status": "done", "screenshot": screenshot_path, "logs": self.logs, "violations": self.violations}
