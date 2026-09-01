import time
import numpy as np
import easyocr
import cv2

print("Loading model...")
t0 = time.time()
reader = easyocr.Reader(['en'], gpu=False)
print(f"Loaded in {time.time()-t0:.2f}s")

img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
print("Running OCR pass 1...")
t1 = time.time()
res = reader.readtext(img, allowlist='0123456789')
print(f"Pass 1 done in {time.time()-t1:.2f}s")
