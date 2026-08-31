import streamlit as st
from core.ocr_engine import process_pipeline

st.set_page_config(page_title="Container OCR App", page_icon="🚢", layout="wide")

st.title("Vertically Stacked Container Number OCR")
st.write("Upload an image of a container to extract its vertically stacked container number.")

# Sidebar for tolerance adjustment
st.sidebar.header("OCR Settings")
x_tolerance = st.sidebar.slider(
    "Vertical Grouping Tolerance (Pixels)", 
    min_value=10, 
    max_value=200, 
    value=150, 
    help="Adjust this if characters in a column are not grouping correctly (e.g. for high resolution images, increase this)."
)

uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Display processing spinner
    with st.spinner('Running EasyOCR Engine...'):
        image_bytes = uploaded_file.read()
        
        # Run the pipeline
        annotated_img, extracted_data = process_pipeline(image_bytes, x_tolerance=x_tolerance)
        
    if annotated_img is not None:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.image(annotated_img, caption="Annotated Image with EasyOCR Bounding Boxes", use_container_width=True)
            
        with col2:
            st.subheader("Extracted Results")
            
            st.text_input("Serial Number :", value=extracted_data.get("Serial Number :", ""), disabled=True)
            st.text_input("Check Number :", value=extracted_data.get("Check Number :", ""), disabled=True)
            st.text_input("Nomor Container :", value=extracted_data.get("Nomor Container :", ""), disabled=True)
            
            grade = extracted_data.get("Grade", "")
            if "Grade : A" in grade:
                st.success(f"**{grade}**")
            elif "Grade : B" in grade:
                st.warning(f"**{grade}**")
            else:
                st.error(f"**{grade}**")
            
    else:
        st.error("Failed to process the image. Ensure it is a valid image file.")
