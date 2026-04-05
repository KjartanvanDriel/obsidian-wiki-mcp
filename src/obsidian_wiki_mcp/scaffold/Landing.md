# Landing

## Projects

```dataview
TABLE status, goal, length(file.inlinks) AS "inlinks"
FROM "work/projects"
WHERE type = "project"
SORT status ASC, file.name ASC
```

## Recent activity

```dataview
TABLE date(file.name, "yyyy-MM-dd") AS "Date"
FROM "work/daily"
SORT file.name DESC
LIMIT 7
```

## Knowledge overview

```dataview
TABLE status, length(file.inlinks) AS "inlinks", length(file.outlinks) AS "outlinks"
FROM "knowledge"
WHERE type
SORT type ASC, status ASC
```
