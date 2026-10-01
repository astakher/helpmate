# Stand-in for Workstream B (routes, file store) - not part of the Part C deliverable
"""The file vault and document Q&A (agent/documents.py).

Uploads are the raw file as the request body (like voice recordings), with the file name in
`?name=`: no multipart parsing, and a size limit that's checked before anything is stored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from helpmate.agent.documents import MAX_BYTES, UnsupportedDocument
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import AnswerOut, AskIn, SourceOut
from helpmate.domain.models import Document

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(current_user)])

EXCERPT_CHARS = 240


@router.get("", response_model=list[Document])
async def list_documents(container: ContainerDep) -> list[Document]:
    return await container.repos.documents.find()


@router.post(
    "",
    response_model=Document,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    request: Request,
    container: ContainerDep,
    name: str = Query(
        min_length=1, max_length=200, description="The file's name, e.g. syllabus.pdf"
    ),
) -> Document:
    """Store a PDF, Word .docx or text/Markdown file and index its text for questions."""
    length = int(request.headers.get("content-length") or 0)
    if length > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That file is over 25 MB.")
    data = await request.body()
    try:
        return await container.library.add(
            name, data, request.headers.get("content-type"), container.clock.now()
        )
    except UnsupportedDocument as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/{document_id}/file", response_class=Response)
async def download(document_id: str, container: ContainerDep) -> Response:
    document = await container.repos.documents.get(document_id)
    data = await container.files.get(document.storage_key) if document else None
    if document is None or data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    quoted = document.name.replace('"', "'")
    return Response(
        data,
        media_type=document.content_type,
        headers={"Content-Disposition": f'inline; filename="{quoted}"'},
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(document_id: str, container: ContainerDep) -> Response:
    if not await container.library.remove(document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ask", response_model=AnswerOut)
async def ask(body: AskIn, container: ContainerDep) -> AnswerOut:
    """Answer from the owner's documents only, citing passages as [n]."""
    answer = await container.library.ask(body.question)
    return AnswerOut(
        answer=answer.text,
        cited=answer.cited,
        sources=[
            SourceOut(
                n=s.n,
                document_id=s.passage.document_id,
                document_name=s.passage.document_name,
                page=s.passage.page,
                excerpt=s.passage.text[:EXCERPT_CHARS]
                + ("…" if len(s.passage.text) > EXCERPT_CHARS else ""),
            )
            for s in answer.sources
        ],
    )
