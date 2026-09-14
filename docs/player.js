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
 *
 * Autoplay: each player starts itself, once, the first time it scrolls at
 * least half into view (IntersectionObserver, threshold 0.5) rather than the
 * instant the page loads — with several players on one page, starting them
 * all at once would be a CPU/noise spike and most would be scrolled past
 * before anyone saw them play. Once a player has auto-started it is
 * unobserved, so scrolling it in and out again never re-triggers it — use
 * the player's own controls to replay. Controls stay visible throughout (an
 * animation that starts itself with no visible way to pause is an
 * accessibility problem). Visitors with `prefers-reduced-motion: reduce` set
 * are left alone entirely: their players wait for a manual click, same as
 * before this feature existed.
 */
(function (global) {
  "use strict";

  var OPTIONS = {
    fit: "width",
    idleTimeLimit: 2,
    theme: "asciinema",
    preload: true
  };

  var prefersReducedMotion = !!(global.matchMedia &&
    global.matchMedia("(prefers-reduced-motion: reduce)").matches);

  var autoplayObserver = null;
  function getAutoplayObserver() {
    if (autoplayObserver || typeof global.IntersectionObserver === "undefined") {
      return autoplayObserver;
    }
    autoplayObserver = new global.IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) {
          return;
        }
        autoplayObserver.unobserve(entry.target);
        var player = entry.target._player;
        if (player && typeof player.play === "function") {
          player.play();
        }
      });
    }, { threshold: 0.5 });
    return autoplayObserver;
  }

  function armAutoplay(el, player) {
    if (prefersReducedMotion || !player) {
      return;
    }
    var observer = getAutoplayObserver();
    if (!observer) {
      return;
    }
    observer.observe(el);
  }

  function createPlayer(el, castPath) {
    var player = global.AsciinemaPlayer.create(castPath, el, OPTIONS);
    el._player = player;
    armAutoplay(el, player);
    return player;
  }

  function initCast(elementId, castPath) {
    var el = document.getElementById(elementId);
    if (!el || !castPath || typeof global.AsciinemaPlayer === "undefined") {
      return;
    }
    createPlayer(el, castPath);
  }

  function initAll() {
    var nodes = document.querySelectorAll("[data-cast]");
    Array.prototype.forEach.call(nodes, function (el) {
      if (typeof global.AsciinemaPlayer === "undefined") {
        return;
      }
      createPlayer(el, el.getAttribute("data-cast"));
    });
  }

  global.initCast = initCast;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})(window);
