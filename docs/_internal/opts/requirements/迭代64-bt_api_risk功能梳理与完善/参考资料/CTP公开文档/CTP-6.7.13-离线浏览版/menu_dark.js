$(document).ready(function() {
    $('#left_menu strong').toggle(
        function () {
            $(this).addClass("left_menu_expand").prev("div").show().animate({width: '+260px'}, "100");
        },
        function () {
            $(this).removeClass("left_menu_expand").prev("div").animate({width: '-260px'}, "100").hide();
        }
    );
});

