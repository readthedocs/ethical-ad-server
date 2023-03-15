import * as jquery from 'jquery';
const ko = require('knockout');


function AdvertisementFormViewModel(method) {
  this.headline = ko.observable($("#id_headline").val());
  this.content = ko.observable($("#id_content").val());
  this.cta = ko.observable($("#id_cta").val());

  this.totalLength = function () {
    let headline = this.headline() || "";
    let content = this.content() || "";
    let cta = this.cta() || "";

    let length = headline.length + content.length + cta.length;

    return length;
  };
}

if ($('form#advertisement-update').length > 0) {
  ko.applyBindings(new AdvertisementFormViewModel());
}
