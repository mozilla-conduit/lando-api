# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

FROM python:3.11

EXPOSE 9000
ENTRYPOINT ["lando-cli"]
CMD ["uwsgi"]
ENV PYTHONUNBUFFERED=1

# Set the MozBuild state path for `mach` autoformatting.
# Avoids any prompts in output during `mach bootstrap`.
ENV MOZBUILD_STATE_PATH /app/.mozbuild

# uWSGI configuration
ENV UWSGI_MODULE=landoapi.wsgi:app \
    UWSGI_SOCKET=:9000 \
    UWSGI_MASTER=1 \
    UWSGI_WORKERS=2 \
    UWSGI_THREADS=8 \
    # Disable worker memory sharing optimizations.  They can cause memory leaks
    # and issues with packages like Sentry.
    # See https://discuss.newrelic.com/t/newrelic-agent-produces-system-error/43446
    UWSGI_LAZY_APPS=1 \
    UWSGI_WSGI_ENV_BEHAVIOR=holy \
    # Make uWSGI die instead of reload when it gets SIGTERM (fixed in uWSGI 2.1)
    UWSGI_DIE_ON_TERM=1 \
    # Check that the options we gave uWSGI are sane
    UWSGI_STRICT=1 \
    # Die if the application threw an exception on startup
    UWSGI_NEED_APP=1

RUN addgroup --gid 10001 app \
    && adduser \
        --disabled-password \
        --uid 10001 \
        --gid 10001 \
        --home /app \
        --gecos "app,,," \
        app

COPY requirements.txt /python_requirements.txt
RUN pip install pip --upgrade
RUN pip install --no-cache -r /python_requirements.txt

COPY migrations /migrations
COPY . /app

# We install outside of the app directory to create the .egg-info in a
# location that will not be mounted over. This means /app needs to be
# added to PYTHONPATH though.
RUN cd / && pip install --no-cache /app
ENV PYTHONPATH /app
RUN chown -R app:app /app

# Create repos directory for transplanting in landing-worker
RUN mkdir /repos

# Run as a non-privileged user
USER app

WORKDIR /app
