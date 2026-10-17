FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
LABEL local.android-build.managed="true"
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64 ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk GRADLE_USER_HOME=/gradle HOME=/tmp/home
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless ca-certificates curl unzip git python3 libstdc++6 && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
USER 10001:10001
