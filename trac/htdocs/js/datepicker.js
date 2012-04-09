jQuery(function($){

    $.fn.datepicker_field = function() {
        $(this).datepicker({
            dateFormat: $.datepicker.ISO_8601
        });
    };

    $('input.datepicker-field').datepicker_field()

});