#!/usr/bin/env sh
#
# Cloudflare Workers Builds build.
#
# arts-link.com's cf-build.sh has to solve a preview-vs-production baseURL
# problem: Hugo bakes baseURL into canonical/og:url/sitemap at build time,
# and a preview build that claims production's URLs is a real harm on a
# public marketing site.
#
# This site doesn't have that problem. hugo.toml sets `private = true`
# unconditionally, which makes every page noindex,nofollow regardless of
# which branch or environment built it — confirmed by a local build, not
# just the config. A preview build looks exactly like production because
# the site never claims to be indexable in the first place. So there's
# nothing to branch on here.
set -eu

# Cloudflare's own tool-detection ("Detected the following tools from
# environment: hugo@X.Y.Z, …") installs the STANDARD Hugo binary, not the
# extended one. Confirmed against a real Workers Builds log: the version
# banner printed no "+extended", and the build ran all the way through
# image processing (12+ minutes) before failing at the very end on
# `resources.Get "/css/main.scss" | toCSS`, because the theme's CSS
# pipeline uses the libsass transpiler, which only exists in the extended
# binary (github.com/nicokaiser/hugo-theme-gallery's layouts/partials/head.html).
#
# Rather than depend on whatever Cloudflare's detector installs — or guess
# at an undocumented env var to request "extended" from it — fetch the real
# extended binary ourselves if the one on PATH isn't it. This is a no-op
# anywhere a proper `hugo_extended` is already installed (e.g. a dev
# machine with it from Homebrew), and only kicks in on a build runner that
# gave us the wrong flavor.
HUGO_VERSION="${HUGO_VERSION:-0.138.0}"

if ! command -v hugo >/dev/null 2>&1 || ! hugo version 2>/dev/null | grep -q '+extended'; then
  echo "cf-build: hugo on PATH is missing (or not extended) — fetching hugo_extended ${HUGO_VERSION}"
  curl -fsSL -o /tmp/hugo.tar.gz \
    "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.tar.gz"
  mkdir -p "$PWD/.hugo-bin"
  tar -xzf /tmp/hugo.tar.gz -C "$PWD/.hugo-bin" hugo
  chmod +x "$PWD/.hugo-bin/hugo"
  export PATH="$PWD/.hugo-bin:$PATH"
  hugo version
fi

exec hugo --minify --gc "$@"
