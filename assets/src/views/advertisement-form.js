import * as jquery from 'jquery';
const ko = require('knockout');


function AdvertisementFormViewModel(method) {
  const MAX_PREVIEW_LENGTH = 100;
  const SENSIBLE_MAXIMUM_LENGTH = 1000;

  const viewmodel = this;

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

  this.imageErrors = function () {
    let image = document.querySelector("#id_image");
    let expected_width = parseInt(image.getAttribute("data-width"));
    let expected_height = parseInt(image.getAttribute("data-height"));

    if (expected_width && expected_height && this.image_width() && this.image_height() &&
        (expected_width != this.image_width() || expected_height != this.image_height())
    ) {
      return 'Expected an image sized ' + expected_width + '*' + expected_height + 'px ' +
             '(it is ' + this.image_width() + '*' + this.image_height() + 'px).';
    }

    return '';
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

  // Handle uploading images cleanly including cropping/resizing
  // and showing the preview
  const upload = document.getElementById("id_image");
  upload.addEventListener('change', e => {
    if (e.target.files.length) {
      for (const file of upload.files) {
        // Get the image width/height
        let imageSrc = URL.createObjectURL(file);
        let tempImage = new Image();
        tempImage.onload = function(ev) {
          viewmodel.image_width(ev.target.width);
          viewmodel.image_height(ev.target.height);
        };
        tempImage.src = imageSrc;

        // Show the image in the ad preview(s)
        document.querySelectorAll(".advertisement-preview img").forEach(element => {
          element.src = imageSrc;
        });
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
