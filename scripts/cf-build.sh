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

exec hugo --minify --gc "$@"
