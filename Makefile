.PHONY: test frontend iso linux-test preview

test:
	.venv/bin/pytest -q

frontend:
	cd frontend && flutter pub get && flutter analyze && flutter test && flutter build web --release --no-web-resources-cdn

iso:
	bash os/build/build.sh

linux-test:
	docker run --rm --platform linux/amd64 -v "$(CURDIR)/tests:/tests:ro" airlink-isp-os:0.1.0-dev bash /tests/linux-integration.sh

preview:
	./scripts/preview.sh
