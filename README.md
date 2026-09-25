# gordon-landreth-photography
Gordon Landreth was my grandfather and an amateur photographer. This is a website I built to share his photo albums with our family and friends.

## Theme
The hugo theme this site is using is [hugo-theme-gallery](https://github.com/nicokaiser/hugo-theme-gallery), and it is included as a module.

## Important Notice
Please respect the ownership of these photos. All images on this website are the property of the family and are not in the public domain. Just because these photos are accessible online does not mean they are free to use, copy, or distribute. We kindly ask that you do not steal or misuse them. Thank you for your understanding and cooperation.

## Deploy

The site is served by a Cloudflare Worker (static assets only, configured in `wrangler.jsonc`). Pushes to `main` build and deploy through Cloudflare Workers Builds. To build or deploy by hand:

```
npm install
npm run cf:build    # hugo --minify --gc
npm run cf:dev      # build, then serve locally on the Workers runtime
npm run cf:deploy   # build, then wrangler deploy
```