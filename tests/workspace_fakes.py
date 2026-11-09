"""An in-memory `Store`: same contract as the Cosmos DB one, no Azure."""
import copy


class InMemoryStore:
    def __init__(self):
        self._projects, self._sessions, self._messages = {}, {}, {}
        self.closed = False

    async def projects(self):
        return copy.deepcopy(list(self._projects.values()))

    async def put_project(self, project):
        self._projects[project["id"]] = copy.deepcopy(project)

    async def delete_project(self, project_id):
        self._projects.pop(project_id, None)

    async def sessions(self):
        return copy.deepcopy(list(self._sessions.values()))

    async def get_session(self, session_id):
        return copy.deepcopy(self._sessions.get(session_id))

    async def put_session(self, session):
        self._sessions[session["id"]] = copy.deepcopy(session)

    async def delete_session(self, session_id):
        self._sessions.pop(session_id, None)
        self._messages.pop(session_id, None)

    async def messages(self, session_id):
        return sorted(copy.deepcopy(list(self._messages.get(session_id, {}).values())), key=lambda m: m["at"])

    async def put_messages(self, session_id, messages):
        bucket = self._messages.setdefault(session_id, {})
        for message in messages:
            bucket[message["id"]] = {**copy.deepcopy(message), "sessionId": session_id}

    async def close(self):
        self.closed = True
