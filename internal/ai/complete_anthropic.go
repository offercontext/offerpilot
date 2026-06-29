package ai

import "context"

// completeAnthropic is implemented in Task 5. Temporary stub so the package
// compiles while the OpenAI adapter (Task 4) is built and tested in isolation.
func (c *Client) completeAnthropic(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	return nil, ErrNotConfigured
}
