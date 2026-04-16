const { z } = require('zod');

const CreateMessageSchema = z.object({
  conversationId: z.string().min(1),
  content: z.string().min(1).max(4000),
  parentId: z.string().optional().nullable(),
});

const ReactionSchema = z.object({
  emoji: z.string().min(1).max(8),
});

module.exports = {
  CreateMessageSchema,
  ReactionSchema,
};
