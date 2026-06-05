# FoodSight
An AI-first Food &amp; Beverage location intelligence platform that transforms Food &amp; Beverage data into a knowledge graph, enabling conversational analytics and interactive map visualizations to help analysts find market opportunities and customers discover restaurants.

## Docker Setup

1. Create a backend environment file:

   ```powershell
   Copy-Item backend\.env.example backend\.env
   ```

2. Update `backend\.env` with your Gemini API key:

   ```env
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```

   To use OpenAI later, set `AI_PROVIDER=openai` and provide `OPENAI_API_KEY`.

3. Build and start the app:

   ```powershell
   docker compose up --build
   ```

4. Open the app:

   - Frontend: http://localhost:5173
   - Backend health check: http://localhost:8000
   - PostgreSQL: localhost:5432

To stop the containers:

```powershell
docker compose down
```

To also remove the PostgreSQL data volume:

```powershell
docker compose down -v
```
