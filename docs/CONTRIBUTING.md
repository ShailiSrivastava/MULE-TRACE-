# Team Collaboration & Contributing Guide

Guide for collaborators **Shaili** and **Raj** working on **MuleTrace**.

---

## 1. Repository Details
- **Repository URL**: `https://github.com/ShailiSrivastava/MULE-TRACE-`
- **Main Branch**: `main`

## 2. Git Workflow

To avoid merge conflicts and keep collaboration smooth, follow this workflow:

1. **Pull Latest Changes Before Starting Work**:
   ```powershell
   git checkout main
   git pull origin main
   ```

2. **Create a Feature Branch**:
   Always work in a feature branch named after what you are building:
   ```powershell
   # Example for Shaili
   git checkout -b feature/graph-visualization

   # Example for Raj
   git checkout -b feature/auth-endpoints
   ```

3. **Keep Commits Clean & Descriptive**:
   Use standard commit prefixes:
   - `feat:` New features
   - `fix:` Bug fixes
   - `docs:` Documentation updates
   - `test:` Adding or updating tests
   - `refactor:` Code improvements without changing functionality

4. **Verify Tests Before Pushing**:
   - Backend:
     ```powershell
     cd backend
     pytest
     ```
   - Frontend:
     ```powershell
     cd frontend
     npm test
     ```

5. **Push and Open a Pull Request**:
   ```powershell
   git push -u origin feature/<your-branch-name>
   ```
   Open a Pull Request on GitHub and request review from your collaborator.

---

## 3. Environment Security Rules

- **NEVER** commit any `.env` file containing secrets, passwords, or production keys.
- If a new environment variable is introduced, add a placeholder entry to `.env.example`, `frontend/.env.example`, and/or `backend/.env.example`.
