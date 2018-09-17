# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


CANNED_DEFAULT_DIFF_CHANGES = [
    {
        "addLines": "3",
        "awayPaths": [],
        "commitHash": None,
        "currentPath": "landoui/templates/revision/404.html",
        "delLines": "3",
        "fileType": "1",
        "hunks": [
            {
                "addLines": None,
                "corpus": (
                    ' {% extends "partials/layout.html" %}\n'
                    "-{% block page_title %}Revision Not "
                    "Available - Lando - Mozilla{% endblock %}\n"
                    "+{% block page_title %}Revision/Diff Not "
                    "Available - Lando - Mozilla{% endblock %}\n"
                    " \n"
                    " {% block main %}\n"
                    ' <main class="NotFoundPage container '
                    'content">\n'
                    " \n"
                    "-  <h1>Revision Not Available</h1>\n"
                    "+  <h1>Revision/Diff Not Available</h1>\n"
                    " \n"
                    "-  <p>The revision you've requested does "
                    "not exist or you do not have permission to "
                    "view it.</p>\n"
                    "+  <p>The revision or diff you've "
                    "requested does not exist or you do not "
                    "have permission to view it.</p>\n"
                    " \n"
                    " </main>\n"
                    " {% endblock %}\n"
                ),
                "delLines": None,
                "isMissingNewNewline": None,
                "isMissingOldNewline": None,
                "newLength": "12",
                "newOffset": "1",
                "oldLength": "12",
                "oldOffset": "1",
            }
        ],
        "id": "6731",
        "metadata": {"line:first": 2},
        "newProperties": [],
        "oldPath": "landoui/templates/revision/404.html",
        "oldProperties": [],
        "type": "2",
    }
]

CANNED_RAW_DEFAULT_DIFF = """
diff --git a/landoui/templates/revision/404.html b/landoui/templates/revision/404.html
--- a/landoui/templates/revision/404.html
+++ b/landoui/templates/revision/404.html
@@ -1,12 +1,12 @@
 {% extends "partials/layout.html" %}
-{% block page_title %}Revision Not Available - Lando - Mozilla{% endblock %}
+{% block page_title %}Revision/Diff Not Available - Lando - Mozilla{% endblock %}

 {% block main %}
 <main class="NotFoundPage container content">

-  <h1>Revision Not Available</h1>
+  <h1>Revision/Diff Not Available</h1>

-  <p>The revision you've requested does not exist or you do not have permission to view it.</p>
+  <p>The revision or diff you've requested does not exist or you do not have permission to view it.</p>

 </main>
 {% endblock %}

""".lstrip()
