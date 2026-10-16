Drop a photo per car here as `<car_id>.jpg` (or .png / .webp), e.g.
`kia-pv5-passenger-71-elite-7seat.jpg`. The exporter picks it up on the next
build (`make build`); a car without a file falls back to its `image_url`, then to
its specification row's image (a Carwow render), then to a placeholder.
