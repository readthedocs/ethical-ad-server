import * as jquery from 'jquery';
import Cropper from 'cropperjs';
const ko = require('knockout');


function AdvertisementFormViewModel(method) {
  const MAX_PREVIEW_LENGTH = 100;
  const SENSIBLE_MAXIMUM_LENGTH = 1000;

  const viewmodel = this;
  const image = document.querySelector("#id_image");
  const expected_width = parseInt(image.getAttribute("data-width"));
  const expected_height = parseInt(image.getAttribute("data-height"));
  const uploadInput = document.getElementById("id_image");
  let cropper = null;

  this.headline = ko.observable($("#id_headline").val());
  this.content = ko.observable($("#id_content").val());
  this.cta = ko.observable($("#id_cta").val());

  this.image_width = ko.observable();
  this.image_height = ko.observable();

  this.getHeadlinePreview = function () {
    return (this.headline() || "").slice(0, MAX_PREVIEW_LENGTH) + " ";
  };
  this.getBodyPreview = function () {
    return (this.content() || "").slice(0, MAX_PREVIEW_LENGTH);
  };
  this.getCTAPreview = function () {
    return " " + (this.cta() || "").slice(0, MAX_PREVIEW_LENGTH);
  };

  this.totalLength = function () {
    let headline = this.headline() || "";
    let content = this.content() || "";
    let cta = this.cta() || "";

    let length = headline.length + content.length + cta.length;

    return length;
  };

  this.maxLength = function () {
    // The actual max length passed from the backend form
    let max_length = parseInt($("#id_maximum_text_length").attr("data-maximum-length"));

    // Use a sensible default if nothing present
    if(isNaN(max_length) || max_length <= 0 || max_length > SENSIBLE_MAXIMUM_LENGTH) {
      max_length = MAX_PREVIEW_LENGTH;
    }

    return max_length;
  };

  this.imageIsWrongSize = function () {
    if (expected_width && expected_height && this.image_width() && this.image_height() &&
        (expected_width != this.image_width() || expected_height != this.image_height())
    ) {
      return true;
    }

    return false;
  };

  this.imageErrors = function () {
    if (this.imageIsWrongSize()) {
      return 'Expected an image sized ' + expected_width + '*' + expected_height + 'px ' +
             '(it is ' + this.image_width() + '*' + this.image_height() + 'px).';
    }

    return '';
  };

  this.cropAndResize = function () {
    if (cropper) {
      cropper.getCroppedCanvas({width: expected_width, height: expected_height}).toBlob((blob) => {
        // modified time is required for some reason
        let file = new File([blob], "cropped.png", {type:"image/png", lastModified: new Date().getTime()});
        let container = new DataTransfer();
        container.items.add(file);
        uploadInput.files = container.files;

        // Trigger the change event
        uploadInput.dispatchEvent(new Event('change'));
      });
    }
    $('#modal').modal('hide');

    // Update URL which sends a measurement event
    const url = new URL(window.location);
    url.searchParams.set("crop", "end");
    window.history.pushState({}, null, url);
  };

  // Handle uploading images cleanly including cropping/resizing
  // and showing the preview
  uploadInput.addEventListener('change', e => {
    if (e.target.files.length) {
      for (const file of uploadInput.files) {
        // Get the image width/height
        let imageSrc = URL.createObjectURL(file);
        let tempImage = new Image();
        tempImage.onload = function(ev) {
          viewmodel.image_width(ev.target.width);
          viewmodel.image_height(ev.target.height);
          if (viewmodel.imageIsWrongSize()) {
            const image = document.getElementById('crop-resize-widget');
            const aspectRatio = expected_width / expected_height;
            const containerRatio = 466 / expected_width;  // 466 is the modal width
            image.src = imageSrc;

            if (cropper) {
              // Reset the cropper before creating a new one
              cropper.destroy();
            }

            $('#modal').modal('show');

            // https://github.com/fengyuanchen/cropperjs
            cropper = new Cropper(image, {
              // Height and Width are guaranteed to be >0 here
              // since the image size was checked
              aspectRatio: aspectRatio,
              initialAspectRatio: aspectRatio,
              viewMode: 2,
              autoCropArea: 1,
              rotatable: false,
              minContainerWidth: expected_width * containerRatio,
              minContainerHeight: expected_height * containerRatio,
            });

            // Update URL which sends a measurement event
            const url = new URL(window.location);
            url.searchParams.set("crop", "start");
            window.history.pushState({}, null, url);
          } else {
            // Show the image in the ad preview(s)
            document.querySelectorAll(".advertisement-preview img").forEach(element => {
              element.src = imageSrc;
            });
          }
        };
        tempImage.src = imageSrc;
      }
    }
  });
}

if ($('form#advertisement-update').length > 0) {
  // Setup bindings on the preview
  $(".ea-headline").attr("data-bind", "text: getHeadlinePreview()");
  $(".ea-body").attr("data-bind", "text: getBodyPreview()");
  $(".ea-cta").attr("data-bind", "text: getCTAPreview()");

  ko.applyBindings(new AdvertisementFormViewModel());
}
