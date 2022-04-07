Creating a new migration:
-------------------------

To create a new migration file (e.g. after updating your models), follow these steps:
1. Make sure that your database is created and up to date, by running: 

```
$ docker-compose run lando-api db upgrade
```

2. Generate a new revision by running 

```
$ docker-compose run lando-api db revision --autogenerate --message <describe your change here>
```

3. Repeat step (1) to run your migration.

To check that your migrations are up to date, you can run the following command. The output would show information about the current revision.

```
$ docker-compose run lando-api db show

Rev: 7883d80258fb (head)
Parent: <base>
Path: /app/migrations/versions/7883d80258fb_initial.py

    initial

    Revision ID: 7883d80258fb
    Revises:
    Create Date: 2022-04-07 15:41:46.233567
```
