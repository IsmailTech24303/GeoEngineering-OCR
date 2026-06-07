# GeoEngineering-OCR
Taranan belgelerden/görsellerden Tesseract OCR ile koordinat tablolarının çıkarılmasını otomatikleştiren; eğiklik düzeltme, tablo çizgisi filtreleme, sezgisel doğrulama kontrolleri ve Excel (.xlsx) ile AutoCAD (.dxf) formatlarına aktarım özelliklerine sahip, Streamlit ve OpenCV ile oluşturulmuş gelişmiş bir CBS/Haritacılık yardımcı programı.
# GeoEngineering-OCR 📸📐

**GeoEngineering-OCR** is an OCR-based GIS/geomatics utility built with Python, Streamlit, and OpenCV. It automates the extraction of coordinate tables (Point ID, X, Y, Z) from scanned documents, survey sheets, or field sketches, and converts them into structured Excel files and CAD-ready DXF drawings.

---

## 🚀 Key Features

### Automated Image Preprocessing
- **Deskewing:** Detects document rotation and straightens text for more reliable OCR.
- **Adaptive Thresholding:** Improves readability under uneven lighting, shadows, or glare.
- **Morphological Line Filtering:** Removes grid lines and table borders to reduce OCR errors caused by line interference.

### Geomatics-Specific Parsing
- Designed with Turkish coordinate table conventions in mind.
- Validates coordinate patterns heuristically, such as:
  - **Y** values typically around 6 digits
  - **X** values typically around 7 digits
- Supports automatic **X/Y swap correction** when coordinates are detected in reverse order.
- Performs heuristic **Z (elevation)** detection when elevation values are present.

### Dual Extraction Modes
- **Automatic OCR Pipeline:** Tries multiple Tesseract Page Segmentation Modes (PSM 4, 6, 11, 3) to match different table layouts.
- **Manual Column Cropping:** Lets users manually select custom regions of interest for non-standard layouts.

### Export Options
- Export to **Excel (.xlsx)**
- Export to **AutoCAD / Netcad compatible DXF (.dxf)** with:
  - point placement
  - point labels
  - coordinate-based drawing output

---

## 🛠 Tech Stack

- **Frontend / UI:** Streamlit
- **Image Processing:** OpenCV, Pillow
- **OCR Engine:** Tesseract OCR
- **Data Handling:** Pandas, NumPy
- **CAD Export:** ezdxf

---

## 📦 Installation

### 1) Install Tesseract OCR

#### Ubuntu / Debian
```bash
sudo apt update
sudo apt install tesseract-ocr
