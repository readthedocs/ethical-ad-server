import * as jquery from 'jquery';


if ($('.ea-update-field').length > 0) {
  $('.ea-update-field').click(function () {
    var target = $(this).attr("data-target-field");
    var value = $(this).attr("data-value");
    $(target).val(value);
    return false;
  });
}
