/*
 * latest-release.js
 *
 * Small, dependency-free helper that keeps a static landing page in sync with
 * the latest published GitHub Release for a repo under the
 * "ofirshudari1-ship-it" account, using GitHub's public unauthenticated REST
 * API (no API key needed, no build step).
 *
 * Usage: mark elements with one of these data attributes, where <repo> is the
 * GitHub repo name (e.g. "optiguard", "playnest", "tapact", "snapcap"):
 *
 *   data-gh-version="<repo>"       -> element's text becomes the tag name
 *                                      exactly as GitHub reports it, e.g. "v4.18.0"
 *   data-gh-version-bare="<repo>"  -> same, but without a leading "v", e.g. "4.18.0"
 *                                      (handy for Hebrew phrasing like "גרסה 4.18.0")
 *   data-gh-download="<repo>"      -> element's href is set to the release's
 *                                      .exe asset download URL
 *   data-gh-filename="<repo>"      -> element's text becomes the .exe asset's
 *                                      file name, e.g. "OptiGuard-Setup-4.18.0.exe"
 *   data-gh-size="<repo>"          -> element's text becomes the .exe asset's
 *                                      human-readable size, e.g. "106.8 MB"
 *
 * Resilience: every HTML element carrying one of these attributes must already
 * contain sensible static fallback content (a plausible version string, a
 * working .../releases/latest link, a plausible filename). If the fetch fails
 * for any reason (offline, GitHub down, rate-limited, blocked) that static
 * content is left exactly as it was — nothing is ever cleared or replaced
 * with an error state.
 */
(function () {
  'use strict';

  var GH_OWNER = 'ofirshudari1-ship-it';
  var releaseCache = {};

  function fetchLatestRelease(repo) {
    if (releaseCache[repo]) return releaseCache[repo];
    releaseCache[repo] = fetch(
      'https://api.github.com/repos/' + GH_OWNER + '/' + repo + '/releases/latest',
      { headers: { Accept: 'application/vnd.github+json' } }
    ).then(function (res) {
      if (!res.ok) throw new Error('GitHub API responded ' + res.status + ' for ' + repo);
      return res.json();
    });
    return releaseCache[repo];
  }

  function findExeAsset(release) {
    if (!release || !Array.isArray(release.assets)) return null;
    for (var i = 0; i < release.assets.length; i++) {
      if (/\.exe$/i.test(release.assets[i].name)) return release.assets[i];
    }
    return null;
  }

  function formatSize(bytes) {
    if (!bytes || typeof bytes !== 'number') return '';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function applyRelease(repo, release) {
    var version = release && release.tag_name ? String(release.tag_name) : '';
    var versionBare = version.replace(/^v/i, '');
    var asset = findExeAsset(release);

    if (version) {
      document.querySelectorAll('[data-gh-version="' + repo + '"]').forEach(function (el) {
        el.textContent = version;
      });
      document.querySelectorAll('[data-gh-version-bare="' + repo + '"]').forEach(function (el) {
        el.textContent = versionBare;
      });
    }

    if (asset) {
      document.querySelectorAll('[data-gh-download="' + repo + '"]').forEach(function (el) {
        el.setAttribute('href', asset.browser_download_url);
      });
      document.querySelectorAll('[data-gh-filename="' + repo + '"]').forEach(function (el) {
        el.textContent = asset.name;
      });
      var size = formatSize(asset.size);
      if (size) {
        document.querySelectorAll('[data-gh-size="' + repo + '"]').forEach(function (el) {
          el.textContent = size;
        });
      }
    }
  }

  function initRepo(repo) {
    fetchLatestRelease(repo)
      .then(function (release) {
        applyRelease(repo, release);
      })
      .catch(function (err) {
        // Offline, GitHub unreachable, rate-limited, or CORS-blocked: do
        // nothing and keep whatever static fallback is already in the HTML.
        if (window.console && console.warn) {
          console.warn('[latest-release] keeping static fallback for "' + repo + '":', err);
        }
      });
  }

  function collectRepos() {
    var repos = {};
    var selector = '[data-gh-version],[data-gh-version-bare],[data-gh-download],[data-gh-filename],[data-gh-size]';
    document.querySelectorAll(selector).forEach(function (el) {
      var repo =
        el.getAttribute('data-gh-version') ||
        el.getAttribute('data-gh-version-bare') ||
        el.getAttribute('data-gh-download') ||
        el.getAttribute('data-gh-filename') ||
        el.getAttribute('data-gh-size');
      if (repo) repos[repo] = true;
    });
    return Object.keys(repos);
  }

  function init() {
    collectRepos().forEach(initRepo);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
