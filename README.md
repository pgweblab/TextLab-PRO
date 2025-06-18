# 🧠 TextLab Pro

**TextLab Pro** è un’applicazione desktop sviluppata in PyQt6 che consente di elaborare testi da file `.pdf`, `.docx` e `.txt` tramite OpenAI GPT-4o.

Affronta uno dei principali limiti dell’uso dell’intelligenza artificiale generativa: l’impossibilità di elaborare contenuti troppo lunghi in una singola richiesta. TextLab Pro suddivide automaticamente i testi in blocchi compatibili con i limiti token dei modelli, li processa uno ad uno, e restituisce risultati coerenti per ogni modalità selezionata.

---

## ✅ Funzionalità principali

- 📂 Caricamento di file `.txt`, `.docx`, `.pdf`
- 🔍 Estrazione testo con OCR (EasyOCR) per PDF non digitali
- 🧠 Elaborazione multi-blocco compatibile con limiti token GPT
- 🛠️ Modalità di AI:
  - Correzione
  - Riassunto
  - Miglioramento
  - Umanizzazione
  - Semplificazione
  - Prompt personalizzati
- 🎨 Interfaccia moderna PyQt6 con tema chiaro/scuro
- ✂️ Segmentazione automatica in blocchi di ~80 parole
- 📥 Drag & Drop, salvataggio risultati `.txt`, supporto multi-tab

---

## 🚀 Installazione

```bash
pip install -r requirements.txt
python main.py
