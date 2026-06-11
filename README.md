# FoodSight
An AI-first Food &amp; Beverage location intelligence platform that transforms Food &amp; Beverage data into a knowledge graph, enabling conversational analytics and interactive map visualizations to help analysts find market opportunities and customers discover restaurants.

## Docker Setup

1. Create a backend environment file:

   ```powershell
   backend\.env.example backend\.env
   ```

2. Update `backend\.env` with your LLM configuration:

   ```env
   LLM_API_STYLE=content
   LLM_API_URL=https://your-llm-endpoint/v1/models/{model}:generateContent
   LLM_API_KEY=your_llm_api_key_here
   LLM_MODEL=your_llm_model
   NEO4J_EXECUTE_QUERIES=false
   ```

   Supported `LLM_API_STYLE` values are `content`, `responses`, and `chat`.
   Set the URL, key, model, and style required by your chosen LLM endpoint.

   FoodSight now generates a schema-aware Neo4j Cypher query for every chat
   message and displays it in the AI response so you can verify the query first.
   Keep `NEO4J_EXECUTE_QUERIES=false` while your knowledge graph is still being
   built. When the graph is ready, set:

   ```env
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=foodsight123
   NEO4J_DATABASE=neo4j
   NEO4J_SCHEMA_PATH=app/knowledge_graph/schema.txt
   NEO4J_EXECUTE_QUERIES=true
   ```


   The graph schema is stored in
   `backend/app/knowledge_graph/schema.txt`. Update that file whenever your
   Neo4j labels, properties, or relationships change.

3. Build and start the app:

   ```powershell
   docker compose up --build
   ```

4. Open the app:

   - Frontend: http://localhost:5173
   - Backend health check: http://localhost:8000
   - PostgreSQL: localhost:5432
   - Neo4j Browser: http://localhost:7474

To stop the containers:

```powershell
docker compose down
```

To also remove the PostgreSQL data volume:

```powershell
docker compose down -v
```
