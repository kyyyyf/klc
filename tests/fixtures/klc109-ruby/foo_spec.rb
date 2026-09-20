require_relative "foo"

RSpec.describe "foo" do
  it "returns 42" do
    expect(foo).to eq(42)
  end
end
