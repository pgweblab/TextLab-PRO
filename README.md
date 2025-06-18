# 🧠 TextLab Pro

**TextLab Pro** è un’applicazione desktop in PyQt6 per l’elaborazione intelligente di testi da file `.pdf`, `.docx` e `.txt`, tramite modelli OpenAI come GPT-4o.  
Supera il limite della lunghezza dei contenuti AI-friendly segmentando automaticamente i testi in blocchi compatibili con i token massimi ammessi.

> ⚠️ **È obbligatorio disporre di una chiave API OpenAI valida**. Il sistema non funziona senza una `API key` attiva e associata al proprio account OpenAI.

---

## ✅ Funzionalità principali

- 📂 Caricamento di file `.txt`, `.docx`, `.pdf`
- 🔍 Estrazione OCR automatica per PDF non digitali (EasyOCR)
- ✂️ Suddivisione automatica in blocchi compatibili con i limiti token GPT
- 🤖 Elaborazione AI per:
  - Correzione
  - Riassunto
  - Riformulazione
  - Miglioramento
  - Semplificazione
  - Formalizzazione
  - Prompt personalizzati
- 🧠 Multi-modalità AI con elaborazione parallela su più blocchi
- 🎨 Interfaccia moderna (chiaro/scuro), supporto drag & drop, multi-tab
- 💾 Salvataggio risultati per ogni modalità selezionata in `.txt`

---

## 🚀 Installazione

Clona il repository e installa le dipendenze:

```bash
git clone https://github.com/tuo-utente/textlab-pro.git
cd textlab-pro
pip install -r requirements.txt
python main.py
