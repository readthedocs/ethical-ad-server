import * as jquery from 'jquery';
const ko = require('knockout');


function PublisherSettingsViewModel(method) {
    this.payoutMethod = ko.observable(method);
}

if ($('body.publisher-settings').length > 0) {
  ko.applyBindings(new PublisherSettingsViewModel($('#id_payout_method').val()));
}
