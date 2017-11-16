# Lando API

A microservice that transforms Phabricator revisions into Autoland
[Transplant][] requests.

Part of Mozilla [Conduit][], our code-management microservice ecosystem.

## Building the service

### Prerequisites

* [docker][] and [docker-compose][] (on OS X and Windows you should use
  the full [Docker for Mac][] or [Docker for Windows][] systems,
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

```
$ docker-compose up -d
```

To create a database:

```
$ invoke upgrade
```

You can use a tool like [httpie][] to test the service.

To stop the containers run
```
$ docker-compose down
```

## Browsing the API documentation

Start the development services and visit http://localhost:8888/ui/ in your
browser to view the API documentation.

## Testing

lando-api's tests use `pytest` with `pytest-flask`, executed within a
Docker container.  The tests are located in `./tests/`.  You can run
all of them via `invoke`:

```
$ invoke test
```

You can provide options to pytest in `testargs` argument:
```
$ invoke test --testargs tests/test_landings.py
```
Please wrap the testargs with `""` if more than one is needed.

Subsets of the tests, e.g. linters, and other commands are also available.  Run
`invoke -l` to see all tasks.

## Migrations

### Developer machine

> Please run the `lando-api.db` container before accessing the database.

#### Add a new migration:

```
$ invoke add-migration "{description of applied changes}"
```

#### Upgrade to the newest revision:

```
$ invoke upgrade
```

### Deployed server

Upgrade to the newest migration:

```
$ docker run [OPTIONS] IMAGE upgrade_db
```

## Accessing the database

Run `lando-api.db` container if development containers are down.
```
$ docker-compose up -d lando-api.db
```

Access the database server (password is `password`)
```
$ psql -h localhost --port 54321 --user postgres -d lando_api_dev
Password for user postgres:
```

[Transplant]: https://hg.mozilla.org/hgcustom/version-control-tools/file/tip/autoland
[Conduit]: https://wiki.mozilla.org/EngineeringProductivity/Projects/Conduit
[docker]: https://docs.docker.com/engine/installation/
[docker-compose]: https://docs.docker.com/compose/install/
[Docker for Mac]: https://docs.docker.com/docker-for-mac/install/
[Docker for Windows]: https://docs.docker.com/docker-for-windows/install/
[Homebrew formula]: http://brewformulas.org/pyinvoke
[docker-compose.override.yml]: https://docs.docker.com/compose/extends/
[httpie]: http://httpie.org/
