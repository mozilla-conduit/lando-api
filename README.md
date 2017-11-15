# Lando API

A microservice that transforms Phabricator revisions into Autoland
[Transplant][] requests.

Part of Mozilla [Conduit][], our code-management microservice ecosystem.

## Building the service

### Prerequisites

* `docker` and `docker-compose` (on OS X and Windows you should use
  the full [Docker for Mac][] or [Docker for Windows][] systems,
  respectively)
* `pyinvoke`
  * Because `pyinvoke` currently has no backwards-compatibility guarantees,
    it is suggested that you install exactly version 0.21.0 via `pip`:
    `pip install invoke==0.21.0` or `pip install --user invoke==0.21.0`.
  * You can use a virtualenv instead of installing it system wide, but you
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

To create a database:

```bash
$ invoke upgrade
```

To build and start all the services:

```bash
$ docker-compose up
```

### Accessing the development server

You need to tell docker-compose to map the webservice's exposed port to a port
on your docker host system.  Create a file named [docker-compose.override.yml][]
in the project root with these contents:

```yaml
version: '2'
services:
  lando-api:
    ports:
      - 8000:80
```

Now run `docker-compose up` in the project root.

You can use a tool like [httpie][] to test the service.

```
$ http localhost:8000
HTTP/1.0 302 FOUND
Content-Length: 0
Content-Type: application/json
Date: Fri, 28 Apr 2017 00:03:10 GMT
Location: http://localhost:8000/ui/
Server: Werkzeug/0.12.1 Python/3.5.3
```

## Running the tests

lando-api's tests use `pytest` with `pytest-flask`, executed within a
Docker container.  The tests are located in `./tests/`.  You can run
all of them via `invoke`:

```bash
$ invoke test
```

Subsets of the tests, e.g. linters, and other commands are also available.  Run
`invoke -l` to see all tasks.

## Browsing the API documentation

Start a development server and expose its ports as documented above, and visit
`http://localhost:8000/ui/` in your browser to view the API documentation.

## Database migrations

### Developer machine

Add a new migration:

```
$ invoke add-migration {description of applied changes}
```

Upgrade to the newest revision:

```
$ invoke upgrade
```

### Deployed server

Upgrade to the newest migration:

```
$ docker run [OPTIONS] IMAGE upgrade_db
```

[Transplant]: https://hg.mozilla.org/hgcustom/version-control-tools/file/tip/autoland
[Conduit]: https://wiki.mozilla.org/EngineeringProductivity/Projects/Conduit
[Docker for Mac]: https://docs.docker.com/docker-for-mac/install/
[Docker for Windows]: https://docs.docker.com/docker-for-windows/install/
[Homebrew formula]: http://brewformulas.org/pyinvoke
[docker-compose.override.yml]: https://docs.docker.com/compose/extends/
[httpie]: http://httpie.org/
