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
