# OntoAgentQA Demo Frontend

Next.js frontend for the OntoAgentQA demo. It provides a compact chat
workbench for asking Vietnamese natural-language questions and inspecting the
agent trace returned by the FastAPI backend.

## Stack

- Next.js App Router
- TypeScript
- Tailwind CSS v4
- No shadcn dependency

## Run

Install dependencies:

```bash
npm install
```

Create an environment file if you need to override the backend URL:

```bash
cp .env.example .env.local
```

Start the frontend:

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

The backend should be running at:

```text
http://localhost:8000
```

## API Contract

The frontend sends:

```http
POST /api/chat
```

to `NEXT_PUBLIC_API_BASE_URL` and expects the backend response shape already
implemented in `demo/backend`.
