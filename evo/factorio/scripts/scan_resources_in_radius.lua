-- Scan resources in a radius around the player character
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    local radius = args.radius or 50
    
    -- 使用 game.player 或搜索角色
    local surface = game.surfaces[1]  -- nauvis
    local agents = surface.find_entities_filtered{name = "character"}
    
    if #agents == 0 then
        return serialize({error = "no character found"})
    end
    
    local agent = agents[1]
    local pos = agent.position
    
    local resources = surface.find_entities_filtered{
        area = {{pos.x - radius, pos.y - radius}, {pos.x + radius, pos.y + radius}},
        type = "resource"
    }
    
    local result = {}
    for _, res in ipairs(resources) do
        local name = res.name
        if not result[name] then
            result[name] = {count = 0, total_amount = 0}
        end
        result[name].count = result[name].count + 1
        result[name].total_amount = result[name].total_amount + (res.amount or 0)
    end
    
    -- 计算实际的资源类型数量
    local total_types = 0
    for _ in pairs(result) do
        total_types = total_types + 1
    end
    
    return serialize({
        ok = true, 
        radius = radius,
        center = {x = math.floor(pos.x), y = math.floor(pos.y)},
        resources = result,
        total_types = total_types
    })
end
