from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.shortcuts import render
import cv2
import cvlib as cv
import numpy as np
from tensorflow.keras.preprocessing.image import img_to_array
from tensorflow.keras.models import load_model

model = load_model('model/gender_detection.model')
classes = ['man', 'woman']

@require_POST
@csrf_exempt
def gender_detection(request):
    # Check if the request has the file part
    if 'file' not in request.FILES:
        return JsonResponse({'error': 'No file provided'}, status=400)

    file = request.FILES['file']

    # Save the uploaded file to the default storage
    filename = default_storage.save(file.name, ContentFile(file.read()))

    # Read the uploaded image using OpenCV
    img = cv2.imread(default_storage.url(filename))
    
    # Apply face detection
    face, confidence = cv.detect_face(img)

    # List to store results
    results = []

    # Loop through detected faces
    for idx, f in enumerate(face):
        startX, startY, endX, endY = f
        
        # Draw rectangle over the face
        cv2.rectangle(img, (startX, startY), (endX, endY), (0, 255, 0), 2)

        # Crop the detected face region
        face_crop = img[startY:endY, startX:endX]

        if face_crop.shape[0] < 10 or face_crop.shape[1] < 10:
            continue

        # Preprocessing for gender detection model
        face_crop = cv2.resize(face_crop, (96, 96))
        face_crop = face_crop.astype("float") / 255.0
        face_crop = img_to_array(face_crop)
        face_crop = np.expand_dims(face_crop, axis=0)

        # Apply gender detection on face
        conf = model.predict(face_crop)[0]
        idx = np.argmax(conf)
        label = classes[idx]

        label = "{}: {:.2f}%".format(label, conf[idx] * 100)

        results.append({'gender': label, 'startX': startX, 'startY': startY, 'endX': endX, 'endY': endY})

    # Convert int64 to int
    results = [{k: int(v) if isinstance(v, np.int64) else v for k, v in d.items()} for d in results]

    # Return results as JSON
    return JsonResponse({'results': results})