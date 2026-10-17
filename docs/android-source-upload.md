# Direct Android source upload

Android Build MCP accepts either a registered public GitHub repository or a source tree uploaded from an agent's own workspace. Source upload does not require pushing the project to GitHub or storing repository credentials on the build host.

## Package the project

Run at the Android project root and retain the Gradle wrapper files:

```sh
tar -czf /tmp/android-source.tar.gz --exclude=.git --exclude=.gradle --exclude=build --exclude='*/build' --exclude=local.properties .
sha256sum /tmp/android-source.tar.gz
```

The archive must contain `gradlew`. Limits are 100 MiB compressed, 2 GiB expanded and 20,000 files. Absolute and parent-traversal paths, links and special files are rejected.

## Upload and build

1. Call `begin_source_upload` with `filename` (`source.tar.gz`), exact `total_bytes` and lowercase SHA256. The response gives `upload_id` and `chunk_bytes` (192 KiB).
2. Read the archive as bytes, base64 encode each chunk, and call `upload_source_chunk` in order with `upload_id`, current `offset` and `data_base64`. Set the next offset to the returned `received_bytes`. Retry only from the last confirmed offset.
3. Call `submit_source_build` with `upload_id`, module (default `app`), project subdirectory (default `.`), mode (`build`, `test`, `lint`, or `full`) and a unique `idempotency_key`. It validates the complete archive and queues an isolated build. Reuse the same key after an uncertain response; use a new key for changed source or build options.
4. Poll `get_build_status`; inspect `read_build_logs`; download files listed by `get_artifacts` with `read_artifact` and verify the returned SHA256.

Incomplete uploads expire after two hours and can also be removed with `cancel_source_upload`. A successful build removes uploaded source and its intermediate workspace after artifact collection. Failed/interrupted jobs retain the workspace for up to 24 hours; use `cleanup_build` to remove an ended job immediately. APKs and logs retain the existing seven-day policy.

Uploaded Gradle files execute as source code inside the bounded build container. Provide the Android Build MCP token only to trusted agents. Release signing and NDK builds remain unsupported.
