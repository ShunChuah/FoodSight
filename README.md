# FoodSight
An AI-first Food &amp; Beverage location intelligence platform that transforms Food &amp; Beverage data into a knowledge graph, enabling conversational analytics and interactive map visualizations to help analysts find market opportunities and customers discover restaurants.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- An OpenAI API key

## Setup

1. Create the environment file (one `.env` in the project root, for the backend and the frontend):

   ```powershell
   copy .env.example .env
   ```

2. In `.env`, fill in section 1 ("Required"): `LLM_API_KEY` (your OpenAI API key), `AUTH_SECRET` and
   `GUARDRAIL_TOKEN_SECRET` (any long random text), and your PostgreSQL password.

3. Load the graph data into Neo4j. Put the Neo4j 5 Community dump at
   `neo4j\imports\neo4j.dump`, then run:

   ```powershell
   docker compose up -d neo4j
   docker compose stop neo4j
   docker run --rm --mount type=volume,source=foodsight_neo4j_data,target=/data --mount "type=bind,source=${PWD}\neo4j\imports,target=/backups,readonly" neo4j:5-community neo4j-admin database load --from-path=/backups --overwrite-destination=true neo4j
   ```

4. Build and start everything:

   ```powershell
   docker compose up --build
   ```

5. Open:

   | Service | URL |
   |---|---|
   | Frontend | http://localhost:5173 |
   | Backend | http://localhost:8000 |
   | Neo4j Browser | http://localhost:7474 (neo4j / foodsight123) |
   | PostgreSQL | localhost:5432 |

## Stopping

```powershell
docker compose down      # stop containers
docker compose down -v   # also delete database volumes
```
