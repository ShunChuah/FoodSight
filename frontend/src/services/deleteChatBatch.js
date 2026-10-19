// Keep successful deletions even if another request fails, so the UI can show
// the remaining chats and retry them without claiming the whole batch succeeded.
export async function deleteChatBatch(chatIds, deleteChat) {
  const results = await Promise.allSettled(chatIds.map(async (id) => {
    await deleteChat(id);
    return id;
  }));
  return {
    deletedIds: results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []),
    failedIds: chatIds.filter((_, index) => results[index].status === "rejected"),
  };
}
