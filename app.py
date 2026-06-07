import os
os.environ["OMP_THREAD_LIMIT"] = "1" # Tesseract'ın tüm CPU çekirdeklerini sömürmesini engeller
import streamlit as st
import pandas as pd
import pytesseract
import cv2
import numpy as np
from PIL import Image
import re
import io
import time

# EĞER WINDOWS KULLANIYORSANIZ ve Tesseract hata verirse, aşağıdaki satırın yorumunu kaldırıp kendi yolunuzu girin:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

try:
    from streamlit_cropper import st_cropper
    HAS_CROPPER = True
except ImportError:
    HAS_CROPPER = False

# OCR Hata Düzeltme Sözlüğü (Sayısal ağırlıklı bölgeler için karakter onarımı)
OCR_FIX_MAP = {
    'S': '5', 's': '5',
    'G': '6', 'g': '6',
    'I': '1', 'i': '1',
    'B': '8', 'Z': '2', 'z': '2',
    'O': '0', 'o': '0',
    'A': '4', 'T': '7',
    'v': '1', 'V': '1',
    'l': '1', '|': '1'
}

st.set_page_config(page_title="Harita OCR Koordinat Okuyucu", layout="wide")

st.title("📸 Haritacılık İçin Kağıttan Koordinat OCR Uygulaması")
st.write("Basılı kağıt üzerindeki nokta numarası ve X, Y, Z koordinat verilerini taratıp otomatik olarak Excel formatına dönüştürün.")

# Görsel Yükleme Alanı
uploaded_image = st.file_uploader("Nokta listesi içeren resim/tarama dosyasını seçin (.png, .jpg, .jpeg)", type=["png", "jpg", "jpeg"])

def preprocess_image(image):
    """Görüntüyü OCR kalitesini artırmak için gri tonlama ve eşikleme işlemlerinden geçirir."""
    # PIL Image nesnesini OpenCV formatına (numpy array) dönüştür
    img_array = np.array(image)
    # RGB'den BGR'ye çevir (OpenCV standardı)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # --- STRATEJİ 2: EĞİKLİK DÜZELTME (DESKEWING) ---
    # Metin satırlarını yatay düzleme paralel hale getirmek için eğikliği tespit et ve düzelt
    thresh_pre = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh_pre > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
    # --- STRATEJİ 1: ADAPTIVE THRESHOLDING ---
    # Lokal ışık farklarını (gölge/parlama) dengelemek için Adaptive Thresholding
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 21, 11
    )

    # --- TABLO ÇİZGİLERİNİ TEMİZLEME ---
    # 1. Yatay çizgileri sil (Daha kalın maske ile)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
    remove_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    cnts = cv2.findContours(remove_horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    for c in cnts:
        cv2.drawContours(thresh, [c], -1, (0, 0, 0), 3)

    # 2. Dikey çizgileri sil (Sayılarla birleşmesini engellemek için agresif silme)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50))
    remove_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    cnts = cv2.findContours(remove_vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    for c in cnts:
        cv2.drawContours(thresh, [c], -1, (0, 0, 0), 3)

    # Sonuç olarak görüntüyü tekrar orijinal haline (Siyah Yazı, Beyaz Arka Plan) çevir
    result = cv2.bitwise_not(thresh)
    return result

def parse_coordinate_text(text, is_2d=False):
    """OCR'dan gelen ham metni satır satır işleyerek Nokta Adı, Y, X, Z sütunlarına ayırır."""
    # 1. Sayısal değerlerin arasına giren hatalı boşlukları temizle
    text = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', text)

    def smart_fix(s):
        for k, v in OCR_FIX_MAP.items():
            s = s.replace(k, v)
        return s

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    parsed_data = []
    last_point_num = 0

    # Türkiye Standartları (Heuristik Kontrol): Y ~ 6 hane, X ~ 7 hane
    Y_MIN, Y_MAX = 200000, 999999
    X_MIN, X_MAX = 3000000, 5000000

    y_pattern = r'(\d{6})\.(\d{1,3})|(\d{6})(\d{3})'
    x_pattern = r'(\d{7})\.(\d{1,3})|(\d{7})(\d{3})'

    for line in lines:
        if any(keyword in line.lower() for keyword in ["nokta", "adı", "sağa", "yukarı", "---"]):
            continue
        
        fixed_line = smart_fix(line)
        y_match = re.search(y_pattern, fixed_line)
        x_match = re.search(x_pattern, fixed_line)

        if y_match and x_match:
            y_raw = y_match.group(0)
            x_raw = x_match.group(0)
            
            if '.' not in y_raw and len(y_raw) == 9:
                y_val = float(y_raw[:6] + "." + y_raw[6:])
            else:
                try: y_val = float(y_raw)
                except: continue

            if '.' not in x_raw and len(x_raw) == 10:
                x_val = float(x_raw[:7] + "." + x_raw[7:])
            else:
                try: x_val = float(x_raw)
                except: continue
            
            # Heuristik: Eğer Y ve X yer değiştirmişse swap yap (Sanity Check)
            if not (Y_MIN <= y_val <= Y_MAX) and (X_MIN <= y_val <= X_MAX):
                y_val, x_val = x_val, y_val
            
            if not (Y_MIN <= y_val <= Y_MAX) or not (X_MIN <= x_val <= X_MAX):
                continue # Geçersiz değerler, satırı atla

            # Nokta Adı Ayıklama (Replace Metodu)
            name_candidate = fixed_line.replace(y_raw, "").replace(x_raw, "").strip()
            p_name = re.sub(r'^[.\-\s]+|[.\-\s]+$', '', name_candidate)

            if not p_name or len(p_name) > 12: # ID çok uzunsa hata olabilir, sayaç kullan
                p_name = str(last_point_num + 1)
            
            row_dict = {"Nokta Adı": p_name, "Y (Sağa)": y_val, "X (Yukarı)": x_val}
            
            # Sayaç Takibi
            if p_name:
                digits = re.findall(r'\d+', p_name)
                if digits: 
                    try: last_point_num = int(digits[0])
                    except: last_point_num += 1
                else:
                    last_point_num += 1
            
            # Z (Kot) Kontrolü (Sadece 2D değilse ara)
            if not is_2d:
                # Y ve X haricindeki sayısal değerleri ara
                other_nums = re.findall(r'\b\d{1,4}\.\d{1,3}\b|\b\d{1,4}\b', line)
                # Y ve X değerlerini listeden çıkar, geriye kalan potansiyel Z'dir
                for val in other_nums:
                    f_val = float(val)
                    if f_val != y_val and f_val != x_val and f_val < 5000: # Kotlar genelde daha küçüktür
                        row_dict["Z (Kot)"] = f_val
                        break

            parsed_data.append(row_dict)
    
    # Dinamik Z Sütunu Kontrolü (Eğer is_2d True ise Z zaten eklenmez)
    if parsed_data and not is_2d:
        z_count = sum(1 for r in parsed_data if "Z (Kot)" in r)
        if z_count < len(parsed_data) * 0.5:
            for r in parsed_data:
                r.pop("Z (Kot)", None)
                
    return parsed_data

def format_as_table_string(data_list):
    """Parsed veriyi dikey hizalı ve sabit başlıklı bir metin bloğuna dönüştürür."""
    if not data_list: return ""
    
    has_z = any("Z (Kot)" in row for row in data_list)
    
    # Sütun genişliklerini sabitle: Nokta(15), Y(20), X(20), Z(15)
    header = f"{'Nokta Adı':<15} {'Y (Sağa)':<20} {'X (Yukarı)':<20}"
    if has_z: header += f" {'Z (Kot)':<15}"
    
    separator = "-" * len(header)
    output = [header, separator]
    
    for row in data_list:
        # Her değeri kendi sütun genişliğinde sola yasla (<)
        line = f"{str(row['Nokta Adı']):<15} {row['Y (Sağa)']:<20.3f} {row['X (Yukarı)']:<20.3f}"
        if has_z:
            z_val = row.get("Z (Kot)", "")
            line += f" {str(z_val):<15}"
        output.append(line)
        
    return "\n".join(output)

def create_dxf(data_list):
    """Parsed veriyi AutoCAD/Netcad uyumlu DXF dosyasına dönüştürür."""
    import ezdxf
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    for row in data_list:
        # Haritacılıkta Y (Sağa) = CAD X, X (Yukarı) = CAD Y
        east = row.get("Y (Sağa)", 0)
        north = row.get("X (Yukarı)", 0)
        elev = row.get("Z (Kot)", 0)
        name = str(row.get("Nokta Adı", ""))
        
        # Noktayı ekle ve ismini yanına yaz (0.4 birim yükseklik, 0.2 birim offset)
        msp.add_point((east, north, elev))
        msp.add_text(name, height=0.4).set_placement((east + 0.2, north + 0.2, elev))
        
    buff = io.StringIO()
    doc.write(buff)
    return buff.getvalue()

@st.cache_data(show_spinner=False)
def perform_ocr_cached(processed_img, is_2d):
    """
    OCR motorunu cache'ler ve işlemleri bir kuyruk mantığıyla sırayla yapar.
    Bu sayede işlemci yükünü azaltır ve mükerrer çalıştırmaları engeller.
    """
    # PSM 4 (Sütun/Tablo yapısı) bu dataset için en güvenilir başlangıçtır.
    psm_modes = [4, 6, 11, 3]
    initial_rows = []
    raw_text = ""
    
    for psm in psm_modes:
        # Sırayla farklı modları dene (Sıralı kuyruk mantığı)
        custom_config = f'--psm {psm} -c preserve_interword_spaces=1 -c tessedit_char_whitelist=0123456789.P-ABCDEFGHIJKLMNQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        
        # OCR Motoru Çağrısı
        raw_text = pytesseract.image_to_string(processed_img, config=custom_config, lang='eng')
        
        # Metni ayrıştır
        initial_rows = parse_coordinate_text(raw_text, is_2d=is_2d)
        
        # Eğer geçerli veri bulunduysa diğer modları denemeden bitir
        if initial_rows:
            break
            
        time.sleep(0.01) # İşlemciye (Context Switch için) kısa bir nefes aldır
    return initial_rows, raw_text

if uploaded_image is not None:
    # Resmi yükle ve göster
    image = Image.open(uploaded_image)

    # Sidebar Ayarları
    st.sidebar.header("⚙️ OCR Ayarları")
    is_2d_mode = st.sidebar.checkbox("Sadece 2 Boyutlu (Z/Kot Yok)", value=False, help="İşaretlenirse Z koordinatları tamamen yok sayılır.")
    is_manual_mode = st.sidebar.checkbox("Manuel OCR Seçeneği (Nokta sayısı 5'ten fazla ise bunu işaretleyebilirsiniz)", value=False)

    # Dinamik Başlık Listesi
    fields = ["Nokta Adı", "Y (Sağa)", "X (Yukarı)"]
    if not is_2d_mode:
        fields.append("Z (Kot)")

    col_img, col_proc = st.columns(2)

    if is_manual_mode:
        if 'manual_crops' not in st.session_state:
            st.session_state.manual_crops = {}
        if 'current_selecting' not in st.session_state:
            st.session_state.current_selecting = None

        with col_img:
            st.subheader("🖼️ Orijinal Resim Üzerinde Alan Seçimi")
            if not HAS_CROPPER:
                st.error("Manuel seçim için 'streamlit-cropper' kütüphanesi gereklidir.")
                st.image(image, width=700)
            elif st.session_state.current_selecting:
                # Görselin boyutunun değişmesini engellemek için canvas_width sabitlenmiştir.
                # Web tarayıcılarında sağ tık menüsü rezerve olduğu için seçim sol tık sürüklemesi ile yapılır.
                # 'box_color' olarak doküman üzerinde en yüksek kontrastı sağlayan Neon Cyan seçildi.
                cropped_img = st_cropper(
                    image, 
                    realtime_update=True,
                    box_color='#00FFFF', 
                    aspect_ratio=None,
                    key=f"cropper_{st.session_state.current_selecting}",
                    canvas_width=700,
                    should_resize_canvas=False
                )
                st.caption(f"📍 Şu an **{st.session_state.current_selecting}** sütununu işaretliyorsunuz.")
                if st.button(f"✅ {st.session_state.current_selecting} Seçimini Onayla"):
                    st.session_state.manual_crops[st.session_state.current_selecting] = cropped_img
                    st.session_state.current_selecting = None
                    st.rerun()
            else:
                st.image(image, width=700, caption="Seçim yapmak için sağdaki paneli kullanın.")

        with col_proc:
            st.subheader("🎯 Alan Belirleme Paneli")
            for field in fields:
                status = "✅" if field in st.session_state.manual_crops else "⚪"
                if st.button(f"{status} {field} Alanını İşaretle", key=f"btn_{field}"):
                    st.session_state.current_selecting = field
                    st.rerun()
            
            # Tüm seçimler tamamlandıysa "İşle" butonu çıksın
            all_done = all(f in st.session_state.manual_crops for f in fields)
            if all_done and not st.session_state.current_selecting:
                st.success("Tüm alanlar belirlendi.")
                if st.button("Seçili Bölgeleri Tara ve Tabloyu Oluştur 🚀"):
                    with st.spinner("OCR sütun bazlı taranıyor..."):
                            col_results = {}
                            for f in fields:
                                img_part = st.session_state.manual_crops[f]
                                proc_part = preprocess_image(img_part)
                                # PSM 6: Uniform block of text (sütun okumada en verimlisi)
                                txt = pytesseract.image_to_string(proc_part, config='--psm 6')
                                col_results[f] = [l.strip() for l in txt.split('\n') if l.strip()]
                            
                            # Verileri hizalayarak listeye dönüştür
                            max_rows = max(len(l) for l in col_results.values())
                            final_list = []
                            for i in range(max_rows):
                                row = {}
                                for f in fields:
                                    row[f] = col_results[f][i] if i < len(col_results[f]) else ""
                                final_list.append(row)
                            st.session_state.manual_final_data = final_list

    else:
        with col_img:
            st.subheader("🖼️ Yüklenen Orijinal Resim")
            st.image(image, width=700) # Cropper ile aynı genişlikte tutarak kaymayı engelliyoruz
            
            if st.sidebar.checkbox("Görüntü İşleme Önizlemesi", value=False):
                st.image(preprocess_image(image), caption="OCR Önizleme", width=700)

        # Otomatik OCR Akışı
        with st.spinner("Görüntü işleniyor ve metin okunuyor... Lütfen bekleyin..."):
            processed_img = preprocess_image(image)
            initial_rows, raw_text = perform_ocr_cached(processed_img, is_2d_mode)
            formatted_table = format_as_table_string(initial_rows)
            
        with col_proc:
            st.subheader("📝 Düzenlenmiş ve Hizalı Liste")
            st.write("OCR hatalarını aşağıdan düzeltebilirsiniz:")
            st.markdown("<style>textarea { font-family: 'Courier New', monospace !important; font-size: 14px !important; }</style>", unsafe_allow_html=True)
            editable_text = st.text_area("Hizalı Koordinat Tablosu", value=formatted_table, height=350)
            st.session_state.auto_editable_text = editable_text

    # Düzenlenmiş/Okunmuş metni harita formatına göre parse et
    st.markdown("---")
    final_rows = []
    if is_manual_mode:
        final_rows = st.session_state.get('manual_final_data', [])
    elif 'auto_editable_text' in st.session_state and st.session_state.auto_editable_text.strip():
        final_rows = parse_coordinate_text(st.session_state.auto_editable_text, is_2d=is_2d_mode)
    
    if final_rows:
        st.subheader("📊 Dönüştürülen Tablo Önizlemesi")
        df_result = pd.DataFrame(final_rows)

        if not df_result.empty:
            st.success(f"🎉 Başarıyla {len(df_result)} adet nokta verisi tespit edildi!")
            st.dataframe(df_result, use_container_width=True)

            col_dl1, col_dl2 = st.columns(2)
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer: 
                df_result.to_excel(writer, index=False, sheet_name='Koordinatlar')
            excel_buffer.seek(0)
            with col_dl1:
                st.download_button(
                    label="📥 Excel Olarak İndir (.xlsx)",
                    data=excel_buffer,
                    file_name="ocr_koordinat_listesi.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            try:
                dxf_string = create_dxf(df_result.to_dict('records'))
                with col_dl2:
                    st.download_button("📐 DXF Olarak İndir (.dxf)", data=dxf_string, file_name="ocr_koordinat_listesi.dxf", mime="application/dxf")
            except:
                pass
