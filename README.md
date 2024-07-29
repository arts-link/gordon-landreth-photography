# gordon-landreth-photography
Gordon Landreth was my grandfather and an amateur photographer. This is a website I built to share his photo albums with our family and friends.

## Important Notice
Please respect the ownership of these photos. All images on this website are the property of the family and are not in the public domain. Just because these photos are accessible online does not mean they are free to use, copy, or distribute. We kindly ask that you do not steal or misuse them. Thank you for your understanding and cooperation.

## Deploy

To deploy this project to cloudfront, you must be logged into AWS on the arts-link.com account through the cli command `aws configure`

To deploy you need the site built into the public directory already, so make sure you run `hugo`, than just do a normal deploy and run the cloudfront invalidation to clear the edge cache.

```
hugo
hugo deploy
aws cloudfront create-invalidation --distribution-id EPSVMGZTAOYO2 --paths "/*"
```