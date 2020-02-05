// JavaScript requirements
import * as jquery from 'jquery';
import * as bootstrap from 'bootstrap';

// CSS includes
import './scss/index.scss';

// Enable Bootstrap tooltips across the site
$(function () {
  $('[data-toggle="tooltip"]').tooltip()
});
