import * as jquery from 'jquery';
const ko = require('knockout');


function AdvertisementFormViewModel(method) {
  const MAX_PREVIEW_LENGTH = 100;
  const SENSIBLE_MAXIMUM_LENGTH = 1000;

  this.headline = ko.observable($("#id_headline").val());
  this.content = ko.observable($("#id_content").val());
  this.cta = ko.observable($("#id_cta").val());

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
}

if ($('form#advertisement-update').length > 0) {
  // Setup bindings on the preview
  $(".ea-headline").attr("data-bind", "text: getHeadlinePreview()");
  $(".ea-body").attr("data-bind", "text: getBodyPreview()");
  $(".ea-cta").attr("data-bind", "text: getCTAPreview()");

  ko.applyBindings(new AdvertisementFormViewModel());
}
