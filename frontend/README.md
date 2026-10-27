# Frontend: the Angular interface

This directory holds an interactive chessboard and the panel that displays the coach's answer.
The interface calls the FastAPI backend on a relative path (`/api/v1`), so the same build works
behind the nginx proxy of the container and behind the proxy of `ng serve`.

## What it is built on

The interface relies on two public libraries:

- **[ngx-chess-board](https://www.npmjs.com/package/ngx-chess-board)**: the board itself, used
  through its `[size]`, `[lightTileColor]` and `[darkTileColor]` inputs and its `(moveChange)`
  output. According to a comment in `.github/workflows/ci.yml`, version 3.0.0 ships sources
  only, so the lock file pins 2.2.3, an Ivy build that installs on Angular 17 with legacy peer
  resolution (`.npmrc` turns it on).
- **[Angular Material](https://material.angular.io/)**: the toolbar, icons, cards, buttons,
  chips, tooltips, a divider and the loading spinner.

The board also keeps the framework on Angular 17. When the lock file was last raised (commit
`9b2e399`, 2026-10-10), this README recorded that `npm audit` listed four advisories against
Angular itself, fixed only in Angular 20, and advisories against the build tools whose fixes ship
with later major versions of Angular. The audit output is not stored in the repository. The
installed ngx-chess-board 2.2.3 declares Angular 13 as its peer (`^13.2.0`) and runs on Angular
17 only through legacy peer resolution, so moving to Angular 20 would mean replacing the board.
The interface runs on the same machine as the API and is not deployed, so it stays on Angular 17
for now.

The Material theme uses a deep blue and an amber, defined in `src/styles.scss` and exposed to the
components as `--navy` and `--gold`. The icon font comes from the `material-icons` package and is
bundled with the application, so the interface works without internet access, on a conference
network for example.

## Layout

```
src/app/
├── app.component.*              # shell: the title bar
├── chessboard/                  # the board, its controls, the demo positions, the history
├── coach/                       # the answer panel
├── models/agent.models.ts       # types mirroring the API responses
└── services/agent.service.ts    # HTTP calls to the backend
```

`chessboard` holds the state of the game and calls the backend. `coach-panel` displays what it
receives through its inputs. If the panel fetched its own data, the board and the panel could
hold two different states.

## Running it

```powershell
npm install
npm start          # http://localhost:4200, proxying to http://localhost:8000
```

The backend must be running as well: see `../backend/README.md`, or start the whole stack with
the `docker compose up` described in the root README.

## Tests

```powershell
npm test -- --watch=false --browsers=ChromeHeadless
```

The tests cover the HTTP service, the answer panel (loading and error states, the detected
opening, the move put forward, the theoretical moves, the reference games, the engine
evaluation and the tools the agent used), the board component (demonstration positions and
history) and the title bar.

## Building the image

```powershell
docker build -t chess-coach-frontend .
```

The `Dockerfile` builds the application with Node 20, then serves it from an unprivileged nginx
image on port 8080. nginx forwards `/api/` to the backend.
