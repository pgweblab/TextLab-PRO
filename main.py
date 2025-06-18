import sys
import os
import re
import logging
import json
import chardet
import codecs
import unicodedata
from functools import partial
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QPushButton, QTextEdit, QLabel, QFileDialog, QProgressBar,
                           QSplitter, QMessageBox, QFrame, QStackedWidget, QGraphicsDropShadowEffect,
                           QButtonGroup, QLineEdit, QCheckBox, QTabWidget, QDialog, QFormLayout,
                           QGroupBox, QScrollArea)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QThread, QObject, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction, QColor, QIcon, QFont, QPalette, QLinearGradient, QPixmap

# Librerie per l'estrazione del testo
import docx  # Per file .docx
import PyPDF2  # Per file .pdf 
from pdfminer.high_level import extract_text as pdfminer_extract_text
from pdfminer.layout import LAParams
from openai import OpenAI  # Per API OpenAI

# Nuove librerie per OCR
import easyocr
from pdf2image import convert_from_path
import numpy as np
import tempfile
import time

# Dizionario dei prompt predefiniti
default_prompts = {
    "rifacimento": "Riformula il testo",
    "correzione": "Correzione del testo",
    "miglioramento": "Migliora il testo",
    "umanizzazione": "Umanizza il testo",
    "riassunto": "Crea un riassunto conciso del testo mantenendo i punti chiave",
    "ampliamento": "Amplia il testo con maggiori dettagli e informazioni",
    "semplificazione": "Semplifica il testo per renderlo più comprensibile",
    "formalizzazione": "Rendi il testo più formale e professionale",
    "personalizzato": "L'utente può scrivere qui la sua richiesta di elaborazione"
}

# Configurazione logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PromptSettingsDialog(QDialog):
    """Dialog per la modifica dei prompt"""
    def __init__(self, prompts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni Prompt")
        self.setMinimumWidth(600)
        self.prompts = prompts.copy()  # Copia del dizionario dei prompt
        
        # Layout principale
        main_layout = QVBoxLayout(self)
        
        # Area di scorrimento per molti prompt
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        form_layout = QFormLayout(scroll_content)
        
        # Creazione di campi di testo per ogni prompt
        self.prompt_fields = {}
        for key, value in self.prompts.items():
            if key != "personalizzato":
                label = QLabel(key.capitalize())
                text_edit = QTextEdit()
                text_edit.setPlainText(value)
                text_edit.setMinimumHeight(80)
                form_layout.addRow(label, text_edit)
                self.prompt_fields[key] = text_edit
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # Pulsanti di conferma e annullamento
        buttons_layout = QHBoxLayout()
        save_button = ModernButton("Salva", True)
        cancel_button = ModernButton("Annulla", False)
        
        save_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(save_button)
        
        main_layout.addLayout(buttons_layout)
    
    def get_updated_prompts(self):
        """Restituisce i prompt aggiornati"""
        updated_prompts = self.prompts.copy()
        for key, field in self.prompt_fields.items():
            updated_prompts[key] = field.toPlainText()
        return updated_prompts

class APIWorker(QObject):
    """Worker per gestire le chiamate API in un thread separato"""
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    result = pyqtSignal(dict)
    
    def __init__(self, text_blocks, selected_options, prompts):
        super().__init__()
        self.text_blocks = text_blocks
        self.selected_options = selected_options
        self.prompts = prompts
        self.results = {option: [] for option in selected_options}
        
    def process(self):
        total_tasks = len(self.text_blocks) * len(self.selected_options)
        completed_tasks = 0
        
        for option in self.selected_options:
            prompt = self.prompts.get(option, "Elabora il testo")
            for block in self.text_blocks:
                result = self.call_api(block, prompt)
                self.results[option].append(result)
                completed_tasks += 1
                self.progress.emit(completed_tasks)
        
        self.result.emit(self.results)
        self.finished.emit()
    
    def call_api(self, text_block, prompt):
        """Chiamata API OpenAI con il prompt specifico"""
        try:
            # Assicura che il blocco di testo sia codificato correttamente in UTF-8
            if isinstance(text_block, str):
                text_block = text_block.encode('utf-8', errors='replace').decode('utf-8')
                
            client = OpenAI(api_key='sk-XXX')
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"{prompt}"
                    },
                    {"role": "user", "content": f"{text_block}"}
                ]
            )
            if completion.choices and completion.choices[0].message:
                response = completion.choices[0].message.content
                # Assicura che la risposta sia codificata correttamente in UTF-8
                return response.encode('utf-8', errors='replace').decode('utf-8')
            return "Nessuna risposta ottenuta dall'API."
        except Exception as e:
            logging.error(f"Errore generazione articolo: {str(e)}")
            return f"Errore: {str(e)}"

class APIThread(QThread):
    """Thread per eseguire il worker API"""
    def __init__(self, text_blocks, selected_options, prompts):
        super().__init__()
        self.worker = APIWorker(text_blocks, selected_options, prompts)
        self.worker.moveToThread(self)
        
    def run(self):
        self.worker.process()

class TextProcessor:
    """Classe per elaborare i testi e dividerli in blocchi"""
    @staticmethod
    def extract_text_from_file(file_path):
        """Estrae il testo da file di diverso formato"""
        _, ext = os.path.splitext(file_path)
        
        try:
            if ext.lower() == '.txt':
                # Rileva automaticamente l'encoding
                with open(file_path, 'rb') as f:
                    raw_data = f.read()
                    encoding = chardet.detect(raw_data)['encoding'] or 'utf-8'  # Fallback a UTF-8
                
                # Usa codecs per una migliore gestione degli encoding
                with codecs.open(file_path, 'r', encoding=encoding, errors='replace') as file:
                    text = file.read()
                    # Normalizza il testo per gestire meglio gli accenti
                    return unicodedata.normalize('NFC', text)
                
            elif ext.lower() == '.docx':
                doc = docx.Document(file_path)
                paragraphs = []
                for paragraph in doc.paragraphs:
                    if paragraph.text:
                        # Normalizza il testo e assicurati che sia valido UTF-8
                        text = unicodedata.normalize('NFC', paragraph.text)
                        text = text.encode('utf-8', errors='replace').decode('utf-8')
                        paragraphs.append(text)
                return '\n'.join(paragraphs)
                
            elif ext.lower() == '.pdf':
                # Controllo iniziale con metodo tradizionale 
                try:
                    # Tenta prima con pdfminer per documenti digitali con specifiche UTF-8
                    laparams = LAParams()
                    
                    # Usa extract_text con parametri espliciti per UTF-8
                    text = pdfminer_extract_text(
                        file_path,
                        laparams=laparams,
                        codec='utf-8'  # Specifica esplicitamente UTF-8
                    )
                    
                    # Normalizza il testo per gestire meglio gli accenti
                    text = unicodedata.normalize('NFC', text)
                    # Assicura che il testo sia codificato correttamente
                    text = text.encode('utf-8', errors='replace').decode('utf-8')
                    
                    # Se il testo sembra valido e contiene più di 100 caratteri, usalo
                    if text and len(text) > 100:
                        logger.info("Testo estratto con successo utilizzando pdfminer con encoding UTF-8")
                        return text
                    else:
                        # Se il testo è scarso, passa all'OCR
                        logger.info("Testo insufficiente con pdfminer, passaggio a OCR")
                        raise ValueError("Testo insufficiente, provo con OCR")
                except Exception as e:
                    logger.warning(f"Estrazione tradizionale fallita: {str(e)}")
                    # Procedi con OCR
                    pass
                    
                # Usa easyOCR per l'estrazione tramite OCR
                logger.info("Inizio estrazione OCR con easyOCR")
                
                # Inizializza il lettore OCR per italiano e inglese
                # Nota: al primo avvio scaricherà i modelli (può richiedere tempo)
                reader = easyocr.Reader(['it', 'en'], gpu=False)
                
                with tempfile.TemporaryDirectory() as path:
                    logger.info("Conversione PDF in immagini...")
                    images = convert_from_path(file_path, dpi=300)
                    
                    # Estrazione del testo da ogni immagine
                    full_text = []
                    total_pages = len(images)
                    
                    for i, img in enumerate(images):
                        logger.info(f"Elaborazione pagina {i+1}/{total_pages}")
                        
                        # Converti l'immagine Pillow in array NumPy per easyOCR
                        img_np = np.array(img)
                        
                        # Estrai il testo
                        # detail=0 restituisce solo il testo senza coordinate
                        # paragraph=True raggruppa il testo in paragrafi
                        results = reader.readtext(img_np, detail=0, paragraph=True)
                        
                        # Assicurati che ogni risultato sia codificato correttamente in UTF-8
                        sanitized_results = []
                        for r in results:
                            if isinstance(r, str):
                                # Normalizza e codifica correttamente
                                sanitized = unicodedata.normalize('NFC', r)
                                sanitized = sanitized.encode('utf-8', errors='replace').decode('utf-8')
                                sanitized_results.append(sanitized)
                            else:
                                # Se non è una stringa, convertiamo e sanitizziamo
                                sanitized = str(r).encode('utf-8', errors='replace').decode('utf-8')
                                sanitized_results.append(sanitized)
                                
                        # Unisci i risultati
                        page_text = '\n'.join(sanitized_results)
                        full_text.append(page_text)
                        
                    # Unisci il testo di tutte le pagine
                    final_text = '\n\n'.join(full_text)
                    
                    # Post-processing del testo
                    # Normalizza in forma di composizione (NFC) per una migliore resa degli accenti
                    final_text = unicodedata.normalize('NFC', final_text)
                    # Rimuovi caratteri non validi in UTF-8 o sostituiscili
                    final_text = final_text.encode('utf-8', errors='replace').decode('utf-8')
                    final_text = re.sub(r' {2,}', ' ', final_text)  # Riduci spazi multipli
                    
                    logger.info(f"Estrazione OCR completata: {len(final_text)} caratteri estratti")
                    return final_text
                
            else:
                raise ValueError(f"Formato file non supportato: {ext}")
                
        except Exception as e:
            logger.error(f"Errore nell'estrazione del testo: {str(e)}")
            raise
    
    @staticmethod
    def split_into_blocks(text, max_words=80):
        """Divide il testo in blocchi di massimo 500 parole, rispettando frasi e parole"""
        if not text:
            return []
            
        # Assicurati che il testo sia codificato correttamente
        if isinstance(text, str):
            text = text.encode('utf-8', errors='replace').decode('utf-8')
            
        # Dividi il testo in frasi (con riconoscimento di più tipi di punteggiatura)
        sentences = re.split(r'(?<=[.!?:])\s+', text.strip())
        
        blocks = []
        current_block = ""
        current_word_count = 0
        
        for sentence in sentences:
            # Calcola il numero di parole nella frase
            sentence_words = len(re.findall(r'\w+', sentence))
            
            # Se aggiungere questa frase supererebbe il limite e il blocco corrente non è vuoto
            if current_word_count + sentence_words > max_words and current_word_count > 0:
                blocks.append(current_block.strip())
                current_block = sentence
                current_word_count = sentence_words
            else:
                current_block += " " + sentence if current_block else sentence
                current_word_count += sentence_words
        
        # Aggiungi l'ultimo blocco se non è vuoto
        if current_block:
            blocks.append(current_block.strip())
            
        return blocks

class ModernButton(QPushButton):
    """Pulsante con design moderno e responsivo"""
    def __init__(self, text, primary=False, icon=None):
        super().__init__(text)
        self.primary = primary
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Imposta il font
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        self.setFont(font)
        
        # Imposta l'icona se fornita
        if icon:
            self.setIcon(QIcon(icon))
            self.setIconSize(QSize(18, 18))
        
        self.update_style()
    
    def update_style(self):
        """Imposta lo stile basato sul tipo di pulsante"""
        common_style = """
            QPushButton {
                border-radius: 6px;
                padding: 10px 20px;
                font-family: 'Segoe UI';
                font-weight: bold;
            }
            QPushButton:hover {
                transition: background-color 0.3s;
            }
            QPushButton:pressed {
                padding-top: 12px;
            }
            QPushButton:disabled {
                background-color: #DDDDDD;
                color: #999999;
                border: none;
            }
        """
        
        if self.primary:
            self.setStyleSheet(common_style + """
                QPushButton {
                    background-color: #3D5AFE;
                    color: white;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #536DFE;
                }
                QPushButton:pressed {
                    background-color: #304FFE;
                }
            """)
        else:
            self.setStyleSheet(common_style + """
                QPushButton {
                    background-color: #FFFFFF;
                    color: #3D5AFE;
                    border: 1px solid #3D5AFE;
                }
                QPushButton:hover {
                    background-color: #F5F7FF;
                }
                QPushButton:pressed {
                    background-color: #E8F0FE;
                }
            """)

class OptionCheckBox(QCheckBox):
    """Checkbox per le opzioni di elaborazione con stile moderno"""
    def __init__(self, text, option_key, parent=None):
        super().__init__(text, parent)
        self.option_key = option_key
        self.setMinimumHeight(30)
        
        # Imposta il font
        font = QFont("Segoe UI", 10)
        self.setFont(font)
        
        # Stile moderno
        self.setStyleSheet("""
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid #C0C0C0;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 2px solid #3D5AFE;
            }
            QCheckBox::indicator:checked {
                background-color: #3D5AFE;
                border: 2px solid #3D5AFE;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNGRkZGRkYiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBjbGFzcz0ibHVjaWRlIGx1Y2lkZS1jaGVjayI+PHBhdGggZD0iTTIwIDZMOSAxN2wtNS01Ii8+PC9zdmc+);
            }
        """)

class ModernProgressBar(QProgressBar):
    """Barra di progresso con stile moderno"""
    def __init__(self):
        super().__init__()
        self.setTextVisible(False)
        self.setMaximumHeight(6)
        self.setMinimumHeight(6)
        
        self.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #F0F0F0;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #3D5AFE;
                border-radius: 3px;
            }
        """)

class ModernTextEdit(QTextEdit):
    """Text edit con stile moderno e migliorato per la leggibilità"""
    def __init__(self, placeholder="", dark_mode=False):
        super().__init__()
        self.setPlaceholderText(placeholder)
        
        # Imposta il font
        font = QFont("Segoe UI", 11)
        self.setFont(font)
        
        # Imposta lo stile di base
        self.update_style(dark_mode)
    
    def update_style(self, dark_mode=False):
        """Aggiorna lo stile in base al tema"""
        if dark_mode:
            self.setStyleSheet("""
                QTextEdit {
                    background-color: #2D2D30;
                    color: #FFFFFF;
                    border: 1px solid #3F3F46;
                    border-radius: 6px;
                    padding: 12px;
                    selection-background-color: #3D5AFE;
                    selection-color: white;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #3F3F46;
                    width: 10px;
                    border-radius: 5px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #686868;
                    border-radius: 5px;
                    min-height: 20px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none;
                    background: none;
                    height: 0px;
                }
            """)
        else:
            self.setStyleSheet("""
                QTextEdit {
                    background-color: #FFFFFF;
                    color: #333333;
                    border: 1px solid #E0E0E0;
                    border-radius: 6px;
                    padding: 12px;
                    selection-background-color: #3D5AFE;
                    selection-color: white;
                }
                QScrollBar:vertical {
                    border: none;
                    background: #F5F5F5;
                    width: 10px;
                    border-radius: 5px;
                    margin: 0px;
                }
                QScrollBar::handle:vertical {
                    background: #CCCCCC;
                    border-radius: 5px;
                    min-height: 20px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none;
                    background: none;
                    height: 0px;
                }
            """)

class DropTextEdit(ModernTextEdit):
    """Area di testo che accetta drag & drop di file"""
    textDropped = pyqtSignal(str)
    fileDropped = pyqtSignal(str)
    
    def __init__(self, dark_mode=False):
        super().__init__("Trascina qui i file (txt, docx, pdf) o incolla il testo...", dark_mode)
        self.setAcceptDrops(True)
        
        # Migliora l'aspetto per area di drop
        drop_style = """
            QTextEdit {
                border: 2px dashed #CCCCCC;
            }
        """
        self.setStyleSheet(self.styleSheet() + drop_style)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            # Cambia stile durante il drag
            self.setStyleSheet(self.styleSheet().replace("2px dashed #CCCCCC", "2px dashed #3D5AFE"))
            event.acceptProposedAction()
    
    def dragLeaveEvent(self, event):
        # Ripristina stile originale quando il drag esce
        self.setStyleSheet(self.styleSheet().replace("2px dashed #3D5AFE", "2px dashed #CCCCCC"))
        super().dragLeaveEvent(event)
    
    def dropEvent(self, event: QDropEvent):
        mime_data = event.mimeData()
        
        # Ripristina stile originale
        self.setStyleSheet(self.styleSheet().replace("2px dashed #3D5AFE", "2px dashed #CCCCCC"))
        
        if mime_data.hasUrls():
            for url in mime_data.urls():
                file_path = url.toLocalFile()
                if file_path:
                    self.fileDropped.emit(file_path)
                    try:
                        text = TextProcessor.extract_text_from_file(file_path)
                        self.textDropped.emit(text)
                        self.setPlainText(text)
                    except Exception as e:
                        QMessageBox.critical(self, "Errore", f"Impossibile leggere il file: {str(e)}")
        
        elif mime_data.hasText():
            self.setPlainText(mime_data.text())
            self.textDropped.emit(mime_data.text())

class ModernLineEdit(QLineEdit):
    """Campo di testo con stile moderno"""
    def __init__(self, placeholder="", dark_mode=False):
        super().__init__()
        self.setPlaceholderText(placeholder)
        
        # Imposta il font
        font = QFont("Segoe UI", 11)
        self.setFont(font)
        self.setMinimumHeight(40)
        
        # Imposta lo stile di base
        self.update_style(dark_mode)
    
    def update_style(self, dark_mode=False):
        """Aggiorna lo stile in base al tema"""
        if dark_mode:
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #2D2D30;
                    color: #FFFFFF;
                    border: 1px solid #3F3F46;
                    border-radius: 6px;
                    padding: 8px 12px;
                    selection-background-color: #3D5AFE;
                    selection-color: white;
                }
            """)
        else:
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #FFFFFF;
                    color: #333333;
                    border: 1px solid #E0E0E0;
                    border-radius: 6px;
                    padding: 8px 12px;
                    selection-background-color: #3D5AFE;
                    selection-color: white;
                }
            """)

class ModernCard(QFrame):
    """Card con stile moderno ed effetto di elevazione"""
    def __init__(self, title="", dark_mode=False):
        super().__init__()
        
        # Titolo della card
        self.title = title
        
        # Imposta il layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(12)
        
        # Aggiungi titolo se presente
        if title:
            title_label = QLabel(title)
            title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
            self.layout.addWidget(title_label)
        
        # Applica stile
        self.update_style(dark_mode)
    
    def update_style(self, dark_mode=False):
        """Aggiorna lo stile in base al tema"""
        if dark_mode:
            self.setStyleSheet("""
                ModernCard {
                    background-color: #2D2D30;
                    border: 1px solid #3F3F46;
                    border-radius: 8px;
                }
                QLabel {
                    color: #FFFFFF;
                }
            """)
        else:
            self.setStyleSheet("""
                ModernCard {
                    background-color: #FFFFFF;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                }
                QLabel {
                    color: #333333;
                }
            """)
        
        # Applica effetto ombra
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 3)
        self.setGraphicsEffect(shadow)

class StatusIndicator(QLabel):
    """Indicatore di stato con stile moderno"""
    def __init__(self):
        super().__init__()
        self.setFont(QFont("Segoe UI", 10))
        self.setText("Pronto")
        self.setMinimumHeight(28)
        self.setMaximumHeight(28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_style("info")
    
    def update_style(self, status_type="info"):
        """Aggiorna lo stile in base al tipo di stato"""
        base_style = """
            QLabel {
                border-radius: 14px;
                padding: 2px 16px;
            }
        """
        
        if status_type == "success":
            self.setStyleSheet(base_style + """
                QLabel {
                    background-color: #E8F5E9;
                    color: #2E7D32;
                    border: 1px solid #C8E6C9;
                }
            """)
        elif status_type == "error":
            self.setStyleSheet(base_style + """
                QLabel {
                    background-color: #FFEBEE;
                    color: #C62828;
                    border: 1px solid #FFCDD2;
                }
            """)
        elif status_type == "warning":
            self.setStyleSheet(base_style + """
                QLabel {
                    background-color: #FFF8E1;
                    color: #F57F17;
                    border: 1px solid #FFECB3;
                }
            """)
        elif status_type == "info":
            self.setStyleSheet(base_style + """
                QLabel {
                    background-color: #E1F5FE;
                    color: #0277BD;
                    border: 1px solid #B3E5FC;
                }
            """)
        else:  # default/neutral
            self.setStyleSheet(base_style + """
                QLabel {
                    background-color: #F5F5F5;
                    color: #616161;
                    border: 1px solid #E0E0E0;
                }
            """)
        
        # Anima il cambio di stato
        animation = QPropertyAnimation(self, b"geometry")
        animation.setDuration(150)
        current_geometry = self.geometry()
        animation.setStartValue(current_geometry.adjusted(2, 0, -2, 0))
        animation.setEndValue(current_geometry)
        animation.start()

class MainWindow(QMainWindow):
    """Finestra principale dell'applicazione"""
    def __init__(self):
        super().__init__()
        
        self.text_blocks = []
        self.processed_results = {}
        self.dark_mode = False
        self.original_filename = ""
        self.prompts = default_prompts.copy()
        
        self.initUI()
    
    def initUI(self):
        self.setWindowTitle("TextLab Pro")
        self.setGeometry(100, 100, 1280, 800)
        
        # Configura il font principale dell'applicazione
        app_font = QFont("Segoe UI", 10)
        QApplication.setFont(app_font)
        
        # Menu principale
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        view_menu = menubar.addMenu("Vista")
        tools_menu = menubar.addMenu("Strumenti")
        
        # Azioni del menu File
        open_action = QAction("Apri File", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        
        save_action = QAction("Salva Risultato", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_result)
        file_menu.addAction(save_action)
        
        # Azioni del menu Vista
        toggle_theme_action = QAction("Modalità Scura", self)
        toggle_theme_action.setCheckable(True)
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)
        
        # Azioni del menu Strumenti
        edit_prompts_action = QAction("Modifica Prompt", self)
        edit_prompts_action.triggered.connect(self.open_prompt_settings)
        tools_menu.addAction(edit_prompts_action)
        
        # Widget principale
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        # Intestazione con informazioni sul file
        header_card = ModernCard()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.file_info_label = QLabel("Nessun file caricato")
        self.file_info_label.setFont(QFont("Segoe UI", 12))
        
        self.status_indicator = StatusIndicator()
        
        header_layout.addWidget(self.file_info_label, 1)
        header_layout.addWidget(self.status_indicator)
        
        header_card.layout.addLayout(header_layout)
        main_layout.addWidget(header_card)
        
        # Card per le opzioni di elaborazione
        options_card = ModernCard("Modalità di Elaborazione")
        
        # Istruzioni
        instructions_label = QLabel("Seleziona una o più modalità di elaborazione:")
        instructions_label.setFont(QFont("Segoe UI", 10))
        options_card.layout.addWidget(instructions_label)
        
        # Layout a griglia per le checkbox delle opzioni
        options_layout = QHBoxLayout()
        options_layout.setSpacing(10)
        
        # Prima colonna di opzioni
        options_col1 = QVBoxLayout()
        options_col1.setSpacing(8)
        
        # Seconda colonna di opzioni
        options_col2 = QVBoxLayout()
        options_col2.setSpacing(8)
        
        # Creazione delle checkbox per le opzioni
        self.option_checkboxes = {}
        
        # Distribuzione delle opzioni in due colonne
        options_list = list(self.prompts.keys())
        middle_index = len(options_list) // 2
        
        for i, option_key in enumerate(options_list):
            if option_key == "personalizzato":  # Gestiamo questa opzione separatamente
                continue
                
            display_name = option_key.capitalize()
            checkbox = OptionCheckBox(display_name, option_key)
            self.option_checkboxes[option_key] = checkbox
            
            if i < middle_index:
                options_col1.addWidget(checkbox)
            else:
                options_col2.addWidget(checkbox)
        
        # Aggiungi le colonne al layout principale delle opzioni
        options_layout.addLayout(options_col1)
        options_layout.addLayout(options_col2)
        options_layout.addStretch()
        
        options_card.layout.addLayout(options_layout)
        
        # Campo per la richiesta personalizzata
        custom_option_layout = QHBoxLayout()
        self.custom_checkbox = OptionCheckBox("Richiesta Personalizzata", "personalizzato")
        self.custom_prompt_edit = ModernLineEdit(placeholder="Inserisci qui la tua richiesta personalizzata...")
        self.custom_prompt_edit.setEnabled(False)
        
        # Connetti il checkbox personalizzato per abilitare/disabilitare il campo di testo
        self.custom_checkbox.toggled.connect(lambda checked: self.custom_prompt_edit.setEnabled(checked))
        
        custom_option_layout.addWidget(self.custom_checkbox)
        custom_option_layout.addWidget(self.custom_prompt_edit, 1)
        
        options_card.layout.addLayout(custom_option_layout)
        
        # Aggiungi la card delle opzioni al layout principale
        main_layout.addWidget(options_card)
        
        # Contenitore per input e output
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)
        
        # Card di input
        input_card = ModernCard("Testo Originale")
        self.input_text = DropTextEdit()
        self.input_text.textDropped.connect(self.on_text_dropped)
        self.input_text.fileDropped.connect(self.on_file_dropped)
        input_card.layout.addWidget(self.input_text)
        
        # Card di output con TabWidget per mostrare risultati multipli
        output_card = ModernCard("Testo Elaborato")
        self.output_tabs = QTabWidget()
        self.output_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.output_tabs.setDocumentMode(True)
        
        # Stile per i tab
        self.output_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: #F5F5F5;
                border: 1px solid #E0E0E0;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #3D5AFE;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background: #E8F0FE;
            }
        """)
        
        # Tab predefinito
        default_tab = QWidget()
        default_tab_layout = QVBoxLayout(default_tab)
        default_tab_layout.setContentsMargins(0, 0, 0, 0)
        
        self.output_text = ModernTextEdit("Il testo elaborato apparirà qui...")
        default_tab_layout.addWidget(self.output_text)
        
        self.output_tabs.addTab(default_tab, "Risultato")
        output_card.layout.addWidget(self.output_tabs)
        
        content_layout.addWidget(input_card)
        content_layout.addWidget(output_card)
        main_layout.addLayout(content_layout, 1)
        
        # Area controlli
        controls_card = ModernCard()
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        
        self.process_button = ModernButton("Elabora Testo", True)
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.process_text)
        
        self.progress_bar = ModernProgressBar()
        self.progress_bar.setVisible(False)
        
        controls_layout.addStretch()
        controls_layout.addWidget(self.process_button)
        controls_layout.addStretch()
        
        controls_card.layout.addLayout(controls_layout)
        controls_card.layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(controls_card)
    
    def open_prompt_settings(self):
        """Apre la finestra di dialogo per modificare i prompt"""
        dialog = PromptSettingsDialog(self.prompts, self)
        if dialog.exec():
            self.prompts = dialog.get_updated_prompts()
            QMessageBox.information(self, "Prompt Aggiornati", "I prompt sono stati aggiornati con successo.")
    
    def toggle_theme(self, checked):
        """Alterna tra tema chiaro e scuro"""
        self.dark_mode = checked
        self.update_theme()
    
    def update_theme(self):
        """Aggiorna il tema dell'interfaccia"""
        # Palette per l'applicazione
        palette = QPalette()
        
        if self.dark_mode:
            # Colori tema scuro
            palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 60))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(200, 200, 200))
            palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            
            # Stile menu
            self.menuBar().setStyleSheet("""
                QMenuBar {
                    background-color: #252525;
                    color: #FFFFFF;
                }
                QMenuBar::item {
                    background-color: transparent;
                }
                QMenuBar::item:selected {
                    background-color: #3D5AFE;
                    color: #FFFFFF;
                }
                QMenu {
                    background-color: #2D2D30;
                    color: #FFFFFF;
                    border: 1px solid #3F3F46;
                }
                QMenu::item:selected {
                    background-color: #3D5AFE;
                    color: #FFFFFF;
                }
            """)
            
            # Stile per i tab in modalità scura
            self.output_tabs.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background: transparent;
                }
                QTabBar::tab {
                    background: #2D2D30;
                    border: 1px solid #3F3F46;
                    border-bottom: none;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    padding: 8px 12px;
                    margin-right: 2px;
                    color: #CCCCCC;
                }
                QTabBar::tab:selected {
                    background: #3D5AFE;
                    color: white;
                }
                QTabBar::tab:hover:!selected {
                    background: #383838;
                }
            """)
        else:
            # Colori tema chiaro (default)
            palette = QPalette()
            
            # Stile menu
            self.menuBar().setStyleSheet("""
                QMenuBar {
                    background-color: #F5F5F5;
                    color: #333333;
                }
                QMenuBar::item:selected {
                    background-color: #3D5AFE;
                    color: #FFFFFF;
                }
                QMenu {
                    background-color: #FFFFFF;
                    color: #333333;
                    border: 1px solid #E0E0E0;
                }
                QMenu::item:selected {
                    background-color: #3D5AFE;
                    color: #FFFFFF;
                }
            """)
            
            # Stile per i tab in modalità chiara
            self.output_tabs.setStyleSheet("""
                QTabWidget::pane {
                    border: none;
                    background: transparent;
                }
                QTabBar::tab {
                    background: #F5F5F5;
                    border: 1px solid #E0E0E0;
                    border-bottom: none;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    padding: 8px 12px;
                    margin-right: 2px;
                }
                QTabBar::tab:selected {
                    background: #3D5AFE;
                    color: white;
                }
                QTabBar::tab:hover:!selected {
                    background: #E8F0FE;
                }
            """)
        
        # Applica la palette
        QApplication.setPalette(palette)
        
        # Aggiorna i componenti con il tema
        for widget in self.findChildren(ModernCard):
            widget.update_style(self.dark_mode)
        
        self.input_text.update_style(self.dark_mode)
        
        # Aggiorna i widget di output in ciascuna tab
        for i in range(self.output_tabs.count()):
            tab = self.output_tabs.widget(i)
            text_edit = tab.findChild(ModernTextEdit)
            if text_edit:
                text_edit.update_style(self.dark_mode)
        
        self.custom_prompt_edit.update_style(self.dark_mode)
    
    def open_file(self):
        """Apre un file tramite dialogo"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Apri File", 
            "", 
            "Documenti di testo (*.txt *.docx *.pdf)"
        )
        
        if file_path:
            self.process_file(file_path)
    
    def process_file(self, file_path):
        """Elabora il file selezionato"""
        try:
            self.original_filename = os.path.basename(file_path)
            self.file_info_label.setText(f"File: {self.original_filename}")
            
            # Controlla se è un PDF per potenziale OCR
            _, ext = os.path.splitext(file_path)
            if ext.lower() == '.pdf':
                # Mostra indicatore di lavoro in corso
                self.status_indicator.setText("Analisi PDF in corso...")
                self.status_indicator.update_style("info")
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 0)  # Modalità indeterminata
                
                # Aggiorna l'interfaccia per mostrare che l'elaborazione è in corso
                QApplication.processEvents()
                
                # Per file di grandi dimensioni, esegui in un thread separato
                class FileLoadThread(QThread):
                    resultReady = pyqtSignal(str)
                    errorOccurred = pyqtSignal(str)
                    
                    def __init__(self, file_path):
                        super().__init__()
                        self.file_path = file_path
                    
                    def run(self):
                        try:
                            text = TextProcessor.extract_text_from_file(self.file_path)
                            self.resultReady.emit(text)
                        except Exception as e:
                            self.errorOccurred.emit(str(e))
                
                # Crea e avvia il thread
                self.load_thread = FileLoadThread(file_path)
                self.load_thread.resultReady.connect(self.on_file_loaded)
                self.load_thread.errorOccurred.connect(self.on_file_error)
                self.load_thread.finished.connect(lambda: self.progress_bar.setVisible(False))
                self.load_thread.start()
                
            else:
                # Per altri formati, usa il metodo standard
                text = TextProcessor.extract_text_from_file(file_path)
                self.input_text.setPlainText(text)
                self.on_text_dropped(text)
                
                self.status_indicator.setText("File caricato con successo")
                self.status_indicator.update_style("success")
                
        except Exception as e:
            error_msg = str(e)
            QMessageBox.critical(self, "Errore", f"Impossibile leggere il file: {error_msg}")
            self.status_indicator.setText("Errore caricamento file")
            self.status_indicator.update_style("error")
            self.progress_bar.setVisible(False)
            logger.error(f"Errore caricamento file: {error_msg}")

    def on_file_loaded(self, text):
        """Gestisce il completamento del caricamento del file"""
        self.input_text.setPlainText(text)
        self.on_text_dropped(text)
        self.progress_bar.setVisible(False)
        self.status_indicator.setText("File caricato con successo")
        self.status_indicator.update_style("success")

    def on_file_error(self, error_msg):
        """Gestisce gli errori durante il caricamento del file"""
        QMessageBox.critical(self, "Errore", f"Impossibile leggere il file: {error_msg}")
        self.status_indicator.setText("Errore caricamento file")
        self.status_indicator.update_style("error")
        self.progress_bar.setVisible(False)
        logger.error(f"Errore caricamento file: {error_msg}")
    
    def on_file_dropped(self, file_path):
        """Gestisce il file trascinato"""
        self.original_filename = os.path.basename(file_path)
        self.file_info_label.setText(f"File: {self.original_filename}")
    
    def on_text_dropped(self, text):
        """Gestisce il testo caricato o incollato senza dividerlo in blocchi immediatamente"""
        # Verifichiamo solo se c'è del testo valido per abilitare il pulsante
        if text and len(text.strip()) > 0:
            self.process_button.setEnabled(True)
            word_count = len(re.findall(r'\w+', text))
            
            self.status_indicator.setText(f"Testo caricato, {word_count} parole")
            self.status_indicator.update_style("info")
        else:
            self.process_button.setEnabled(False)
            self.status_indicator.setText("Nessun testo valido")
            self.status_indicator.update_style("warning")
    
    def get_selected_options(self):
        """Ottiene le opzioni selezionate dall'utente"""
        selected_options = []
        
        # Raccoglie tutte le opzioni normali selezionate
        for key, checkbox in self.option_checkboxes.items():
            if checkbox.isChecked():
                selected_options.append(key)
        
        # Aggiunge l'opzione personalizzata se selezionata
        if self.custom_checkbox.isChecked():
            selected_options.append("personalizzato")
            # Aggiorna il prompt personalizzato nel dizionario dei prompt
            custom_text = self.custom_prompt_edit.text()
            if custom_text:
                self.prompts["personalizzato"] = custom_text
        
        return selected_options
    
    def create_output_tabs(self, selected_options):
        """Crea le tab per i risultati di ciascuna opzione selezionata"""
        # Rimuovi tutte le tab esistenti
        while self.output_tabs.count() > 0:
            self.output_tabs.removeTab(0)
        
        # Crea una nuova tab per ciascuna opzione selezionata
        for option in selected_options:
            # Crea un widget per la tab
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            
            # Crea un text edit per mostrare il risultato
            text_edit = ModernTextEdit("Elaborazione in corso...", self.dark_mode)
            tab_layout.addWidget(text_edit)
            
            # Aggiungi la tab con nome capitalizzato
            display_name = option.capitalize()
            self.output_tabs.addTab(tab, display_name)
    
    def process_text(self):
        """Elabora il testo corrente in base alle opzioni selezionate"""
        # Ottieni le opzioni selezionate
        selected_options = self.get_selected_options()
        
        if not selected_options:
            QMessageBox.warning(self, "Attenzione", "Seleziona almeno una modalità di elaborazione.")
            return
        
        # Ottieni il testo attuale dall'area di editing
        current_text = self.input_text.toPlainText()
        
        # Verifica se c'è del testo da elaborare
        if not current_text or not current_text.strip():
            QMessageBox.warning(self, "Attenzione", "Nessun testo da elaborare.")
            return
        
        # Dividi il testo in blocchi
        self.text_blocks = TextProcessor.split_into_blocks(current_text)
        
        if not self.text_blocks:
            QMessageBox.warning(self, "Attenzione", "Impossibile dividere il testo in blocchi validi.")
            return
        
        # Crea le tab per i risultati
        self.create_output_tabs(selected_options)
        
        # Mostra informazioni sui blocchi e le opzioni
        block_count = len(self.text_blocks)
        options_count = len(selected_options)
        self.status_indicator.setText(f"Elaborazione di {block_count} blocchi con {options_count} modalità")
        
        # Configura l'interfaccia per l'elaborazione
        self.process_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        total_tasks = len(self.text_blocks) * len(selected_options)
        self.progress_bar.setMaximum(total_tasks)
        self.progress_bar.setValue(0)
        
        self.status_indicator.setText("Elaborazione in corso...")
        self.status_indicator.update_style("info")
        
        # Crea e avvia il thread per le chiamate API
        self.api_thread = APIThread(self.text_blocks, selected_options, self.prompts)
        self.api_thread.worker.progress.connect(self.update_progress)
        self.api_thread.worker.result.connect(self.display_results)
        self.api_thread.worker.finished.connect(self.processing_finished)
        self.api_thread.start()
    
    def update_progress(self, value):
        """Aggiorna la barra di progresso"""
        self.progress_bar.setValue(value)
        total_tasks = len(self.text_blocks) * len(self.get_selected_options())
        self.status_indicator.setText(f"Elaborazione: {value}/{total_tasks}")
    
    def display_results(self, results):
        """Visualizza i risultati dell'elaborazione in tab separate"""
        self.processed_results = results
        
        # Per ciascuna opzione elaborata
        for i, (option, blocks) in enumerate(results.items()):
            # Unisci i blocchi elaborati
            processed_text = "\n\n".join([block for block in blocks if block])
            
            # Trova la tab corrispondente e aggiorna il testo
            tab = self.output_tabs.widget(i)
            if tab:
                text_edit = tab.findChild(ModernTextEdit)
                if text_edit:
                    text_edit.setPlainText(processed_text)
    
    def processing_finished(self):
        """Operazioni da eseguire al termine dell'elaborazione"""
        self.progress_bar.setVisible(False)
        self.process_button.setEnabled(True)
        
        # Controlla se ci sono stati errori nell'elaborazione
        errors = 0
        for option, blocks in self.processed_results.items():
            errors += sum(1 for block in blocks if block and block.startswith("Errore:"))
        
        if errors == 0:
            self.status_indicator.setText("Elaborazione completata")
            self.status_indicator.update_style("success")
        else:
            self.status_indicator.setText(f"Completato con {errors} errori")
            self.status_indicator.update_style("warning")
    
    def save_result(self):
        """Salva il risultato dell'elaborazione corrente in un file"""
        # Controlla se ci sono risultati da salvare
        current_tab_index = self.output_tabs.currentIndex()
        if current_tab_index == -1:
            QMessageBox.warning(self, "Attenzione", "Nessun risultato da salvare.")
            return
        
        # Ottieni il testo dalla tab corrente
        current_tab = self.output_tabs.widget(current_tab_index)
        text_edit = current_tab.findChild(ModernTextEdit)
        if not text_edit or not text_edit.toPlainText():
            QMessageBox.warning(self, "Attenzione", "Nessun testo elaborato da salvare.")
            return
        
        # Genera un nome di file suggerito
        suggested_name = ""
        if self.original_filename:
            name, _ = os.path.splitext(self.original_filename)
            tab_name = self.output_tabs.tabText(current_tab_index).lower()
            suggested_name = f"{name}_{tab_name}.txt"
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Salva Risultato", 
            suggested_name, 
            "Documento di testo (*.txt)"
        )
        
        if file_path:
            try:
                # Usa codecs per una migliore gestione dell'encoding UTF-8
                with codecs.open(file_path, 'w', encoding='utf-8', errors='replace') as file:
                    content = text_edit.toPlainText()
                    # Assicurati che il contenuto sia valido UTF-8 prima del salvataggio
                    content = content.encode('utf-8', errors='replace').decode('utf-8')
                    file.write(content)
                
                self.status_indicator.setText(f"File salvato: {os.path.basename(file_path)}")
                self.status_indicator.update_style("success")
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile salvare il file: {str(e)}")
                self.status_indicator.setText("Errore salvataggio")
                self.status_indicator.update_style("error")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
