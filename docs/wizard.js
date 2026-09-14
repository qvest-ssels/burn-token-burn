/* Install wizard on the homepage: OS tab selection + copy-to-clipboard.
 *
 * All four steps are always in the markup and always visible — this file
 * only (a) swaps which OS's install command is shown, defaulting to a
 * best-effort guess from navigator.platform with a manual click to
 * override, and (b) wires up the "copy" buttons next to each command. With
 * JavaScript disabled the Linux command block (marked up as the default in
 * the HTML) is what a visitor sees, which is also correct for WSL — nothing
 * about the wizard depends on script running. No inline handlers, per this
 * site's strict-CSP rule.
 */
(function (global) {
  "use strict";

  function detectOS() {
    var platform = (global.navigator && (global.navigator.platform || "")) || "";
    var ua = (global.navigator && global.navigator.userAgent) || "";
    if (/mac/i.test(platform) || /Mac OS X/i.test(ua)) {
      return "macos";
    }
    if (/win/i.test(platform) || /Windows/i.test(ua)) {
      return "windows";
    }
    if (/linux/i.test(platform) || /Linux/i.test(ua)) {
      return "linux";
    }
    return "linux"; // default on anything unrecognised (also the WSL case)
  }

  function selectOS(wizard, os) {
    var tabs = wizard.querySelectorAll(".os-tab");
    Array.prototype.forEach.call(tabs, function (tab) {
      var active = tab.getAttribute("data-os") === os;
      tab.setAttribute("aria-current", active ? "true" : "false");
    });
    var blocks = wizard.querySelectorAll("[data-os-block]");
    Array.prototype.forEach.call(blocks, function (block) {
      block.hidden = block.getAttribute("data-os-block") !== os;
    });
  }

  function initWizard() {
    var wizard = document.getElementById("install-wizard");
    if (!wizard) {
      return;
    }
    selectOS(wizard, detectOS());
    var tabs = wizard.querySelectorAll(".os-tab");
    Array.prototype.forEach.call(tabs, function (tab) {
      tab.addEventListener("click", function () {
        selectOS(wizard, tab.getAttribute("data-os"));
      });
    });
  }

  function initCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy-target]");
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener("click", function () {
        var target = document.getElementById(button.getAttribute("data-copy-target"));
        if (!target || !global.navigator.clipboard) {
          return;
        }
        global.navigator.clipboard.writeText(target.textContent.trim()).then(function () {
          var original = button.textContent;
          button.textContent = "copied";
          global.setTimeout(function () {
            button.textContent = original;
          }, 1500);
        }, function () {
          /* clipboard write can fail (permissions, insecure context) —
             leave the button text unchanged, the command is still selectable */
        });
      });
    });
  }

  function init() {
    initWizard();
    initCopyButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
