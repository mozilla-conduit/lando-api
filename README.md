# Lando API

A microservice to land Phabricator revisions to version control
repositories.

Part of Mozilla Conduit, our code-management microservice ecosystem.

[![What's Deployed](https://img.shields.io/badge/whatsdeployed-prod,dev-green.svg)](https://whatsdeployed.io/s-46t)

## Building the service

### Prerequisites

* docker and docker-compose (on OS X and Windows you should use
  the full Docker for Mac or Docker for Windows systems,
  respectively)
* `pyinvoke`
  * Because `pyinvoke` currently has no backward-compatibility guarantees,
    it is suggested that you install exactly version 0.21.0 via `pip`:
    `pip install invoke==0.21.0` or `pip install --user invoke==0.21.0`.
  * You can use a virtualenv instead of installing it system-wide, but you
    should create the virtualenv *outside* of the lando-api source directory so
    that the linter doesn't check the virtualenv files.
  * If you are running Windows, you will need a special file in your user
    directory (typically `C:\Users\<username>\`) called `.invoke.yml`.  It
    should contain the following:

        ```yaml
        run:
          shell: C:\Windows\System32\cmd.exe
        ```

### Running the development server

To build and start the development services containers (remove `-d` if logs
should be printed out):

    ```shell
    docker-compose up -d
    ```

To create a database:

    ```shell
    invoke setup-db
    ```

You can use a tool like httpie to test the service.

To stop the containers run

    ```shell
    docker-compose down
    ```

## Browsing the API documentation

Start the development services and visit `http://localhost:8888/ui/`
in your browser to view the API documentation.

## Testing

lando-api's tests use `pytest` with `pytest-flask`, executed within a
Docker container.  The tests are located in `./tests/`.  You can run
all of them via `invoke`:

    ```shell
    invoke test
    ```

You can provide options to pytest in `testargs` argument:

    ```shell
    invoke test --testargs tests/test_landings.py
    ```

Please wrap the testargs with `""` if more than one is needed.

Subsets of the tests, e.g. linters, and other commands are also available.  Run
`invoke -l` to see all tasks.

## Migrations

### Developer machine

> Please run the `lando-api.db` container before accessing the database.

#### Add a new migration

    ```shell
    invoke add-migration "{description of applied changes}"
    ```

#### Upgrade to the newest revision

    ```shell
    invoke upgrade
    ```

### Deployed server

Upgrade to the newest migration:

    ```shell
    docker run [OPTIONS] IMAGE lando-cli db upgrade
    ```

## Accessing the database

Run `lando-api.db` container if development containers are down.

    ```shell
    docker-compose up -d lando-api.db
    ```

Access the database server (password is `password`)

    ```shell
    $ psql -h localhost --port 54321 --user postgres -d lando_api_dev
    Password for user postgres:
    ```

## Useful Links

[Transplant](https://hg.mozilla.org/hgcustom/version-control-tools/file/tip/autoland)
[Conduit](https://wiki.mozilla.org/EngineeringProductivity/Projects/Conduit)
[docker](https://docs.docker.com/engine/installation/)
[docker-compose](https://docs.docker.com/compose/install/)
[Docker for Mac](https://docs.docker.com/docker-for-mac/install/)
[Docker for Windows](https://docs.docker.com/docker-for-windows/install/)
[Homebrew formula](http://brewformulas.org/pyinvoke)
[docker-compose.override.yml](https://docs.docker.com/compose/extends/)
[httpie](http://httpie.org/)

## Support

To chat with Lando users and developers, join them on [Matrix](https://chat.mozilla.org/#/room/#conduit:mozilla.org).
