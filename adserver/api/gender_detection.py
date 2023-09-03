from tensorflow.keras.preprocessing.image import img_to_array
from tensorflow.keras.models import load_model
import numpy as np
import cv2
import os
import cvlib as cv
from flask import Flask, request, jsonify

# load model
model = load_model('model/gender_detection.model')

classes = ['man','woman']

app = Flask(__name__)

@app.route('/gender_detection', methods=['POST'])
def gender_detection():
    # check if the post request has the file part
    if 'file' not in request.files:
        return 'No file provided', 400

    file = request.files['file']
    if file.filename == '':
        return 'No file selected', 400

    # read image file string data from memory
    filestr = file.read()

    # convert string data to numpy array
    npimg = np.frombuffer(filestr, np.uint8)

    # convert numpy array to image
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

    # apply face detection
    face, confidence = cv.detect_face(img)

    # list to store results
    results = []

    # loop through detected faces
    for idx, f in enumerate(face):
        # get corner points of face rectangle
        (startX, startY) = f[0], f[1]
        (endX, endY) = f[2], f[3]

        # draw rectangle over face
        cv2.rectangle(img, (startX,startY), (endX,endY), (0,255,0), 2)

        # crop the detected face region
        face_crop = np.copy(img[startY:endY,startX:endX])

        if (face_crop.shape[0]) < 10 or (face_crop.shape[1]) < 10:
            continue

        # preprocessing for gender detection model
        face_crop = cv2.resize(face_crop, (96,96))
        face_crop = face_crop.astype("float") / 255.0
        face_crop = img_to_array(face_crop)
        face_crop = np.expand_dims(face_crop, axis=0)

        # apply gender detection on face
        conf = model.predict(face_crop)[0] # model.predict return a 2D matrix, ex: [[9.9993384e-01 7.4850512e-05]]

        # get label with max accuracy
        idx = np.argmax(conf)
        label = classes[idx]

        label = "{}: {:.2f}%".format(label, conf[idx] * 100)

        results.append({'gender': label, 'startX': startX, 'startY': startY, 'endX': endX, 'endY': endY})

        #conv int64
        results = [{k: int(v) if isinstance(v, np.int64) else v for k, v in d.items()} for d in results]

    # return results as JSON
    return jsonify(results)

if __name__ == '__main__':
    app.run()
