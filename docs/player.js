/* Shared asciinema-player bootstrap for every page of this site.
 *
 * The player options live here and only here, so they cannot drift between
 * pages. A page embeds a recording by marking up a container:
 *
 *   <div class="player" id="player-01" data-cast="casts/01-report.cast"></div>
 *
 * and loading this file with <script src="player.js" defer></script>. No
 * inline script is needed anywhere (the site stays strict-CSP safe).
 * initCast('player-01', 'casts/01-report.cast') is available for anything
 * that has to create a player by hand.
 *
 * Player size is controlled by the .player wrapper in style.css, not here:
 * fit: "width" makes the terminal fill whatever width the wrapper allows.
 */
(function (global) {
  "use strict";

  var OPTIONS = {
    fit: "width",
    idleTimeLimit: 2,
    theme: "asciinema"
  };

  function initCast(elementId, castPath) {
    var el = document.getElementById(elementId);
    if (!el || !castPath || typeof global.AsciinemaPlayer === "undefined") {
      return;
    }
    global.AsciinemaPlayer.create(castPath, el, OPTIONS);
  }

  function initAll() {
    var nodes = document.querySelectorAll("[data-cast]");
    Array.prototype.forEach.call(nodes, function (el) {
      if (typeof global.AsciinemaPlayer === "undefined") {
        return;
      }
      global.AsciinemaPlayer.create(el.getAttribute("data-cast"), el, OPTIONS);
    });
  }

  global.initCast = initCast;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})(window);
